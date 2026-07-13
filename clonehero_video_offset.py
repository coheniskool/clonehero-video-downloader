# clonehero_video_offset.py
# pip install audio-offset-finder numpy
# NOTE: numpy must land in the >=2,<=2.4 window on this environment -- numpy 1.26.x
# breaks scipy's C extensions on Python 3.14, and numpy 2.5+ breaks numba (a librosa
# dependency, which audio-offset-finder itself uses internally for MFCC computation).

import json
import os
import subprocess
import tempfile
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
from audio_offset_finder.audio_offset_finder import find_offset_between_files

handler = RotatingFileHandler('clonehero_offset.log', maxBytes=1_000_000, backupCount=5)
logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s - %(levelname)s - %(message)s')

#audio-offset-finder's "standard score" is a z-score of the correlation peak (standard
#deviations above the mean of the correlation curve) -- a very different scale from the
#old DTW confidence_ratio this replaces. 0.5 was the default confirmed during /spec
#review, before this backend was empirically tested; a smoke test against a clean
#synthetic signal (Task 5 commit) scored ~8.8, so 0.5 may be far too permissive to
#ever flag a genuinely weak match. Flagged for recalibration once Task 12's
#real-library validation provides real-world scores to tune against -- not changed
#here without asking, per the spec's "ask first" boundary on this threshold.
MIN_STANDARD_SCORE = 0.5

#Clone Hero's own convention for the full mixed track. Multitrack charts also
#ship isolated stems (drums.ogg, crowd.ogg, vocals.ogg, ...) that must NOT be
#used as the alignment reference -- their onset pattern doesn't correspond to
#the video's full mix at all.
FULL_MIX_NAMES = ('song.ogg', 'song.opus', 'song.mp3', 'song.wav')
#Only Clone Hero's officially recognized background-video filenames.
VIDEO_NAMES = ('video.mp4', 'video.avi', 'video.webm', 'video.ogv')


def find_song_audio(song_dir):
    #filename is always "song*" regardless of numeric suffix -- some libraries use
    #"song.ogg", others "song_1877.ogg" from a different chart source. Glob instead
    #of matching FULL_MIX_NAMES exactly so ID-suffixed folders aren't silently skipped.
    for ext in ('.ogg', '.opus', '.mp3', '.wav'):
        matches = sorted(song_dir.glob('song*' + ext))
        if matches:
            return matches[0]
    #No dedicated full-mix file -- only safe to use a stem if it's the only track present.
    audio_files = [f for f in song_dir.glob('*') if f.suffix.lower() in {'.ogg', '.mp3', '.wav', '.opus'}]
    return audio_files[0] if len(audio_files) == 1 else None


def find_song_ini(song_dir):
    #also inconsistently named across the library ("song.ini" vs "song_2400.ini") -- there
    #is always exactly one *.ini file per song folder regardless of chart source, so match
    #on that, preferring the literal "song.ini" name when more than one .ini exists.
    ini_files = sorted(song_dir.glob('*.ini'))
    if not ini_files:
        return None
    return next((p for p in ini_files if p.name.lower() == 'song.ini'), ini_files[0])


def find_video_file(song_dir):
    for name in VIDEO_NAMES:
        candidate = song_dir / name
        if candidate.exists():
            return candidate
    return None


#Clone Hero requires these exact literal filenames -- confirmed against the
#official wiki (Adding Custom Songs / song.ini Guide). A folder whose .ini or
#chart file is numeric-ID-suffixed (song_2400.ini, notes_454.chart) instead of
#literal can't be loaded by the game at all, regardless of file content being
#otherwise correct.
CANONICAL_CHART_NAMES = {'song.ini', 'notes.chart', 'notes.mid'}


def scan_song_folder_chart_names(song_dir):
    """Detect (but do not verify or rename) ID-suffixed chart filenames.

    Returns {'status': ..., 'detail': ...} where status is one of:
    'ok' (song.ini and a notes.chart/.mid are both present with literal
    names), 'id_suffixed' (the .ini and/or chart file is numeric-ID-suffixed
    -- detail lists which), 'no_ini' (no *.ini file at all), 'no_chart_file'
    (a literal or ID-suffixed .ini exists but no notes.chart/.mid does).

    This is detection only -- verifying that an ID-suffixed file's content
    actually matches the folder's stated song (Tasks 2/3), and the rename/
    collision/relocation logic (Task 4), are separate steps layered on top.
    """
    ini_files = sorted(song_dir.glob('*.ini'))
    if not ini_files:
        return {'status': 'no_ini', 'detail': ''}

    ini_file = next((p for p in ini_files if p.name.lower() == 'song.ini'), ini_files[0])

    chart_files = sorted(song_dir.glob('notes.chart')) + sorted(song_dir.glob('notes.mid'))
    chart_file = next((p for p in chart_files if p.name.lower() in ('notes.chart', 'notes.mid')), None)
    if chart_file is None:
        chart_candidates = sorted(song_dir.glob('notes_*.chart')) + sorted(song_dir.glob('notes_*.mid'))
        chart_file = chart_candidates[0] if chart_candidates else None

    if chart_file is None:
        return {'status': 'no_chart_file', 'detail': ini_file.name}

    id_suffixed = [
        p.name for p in (ini_file, chart_file)
        if p.name.lower() not in CANONICAL_CHART_NAMES
    ]
    if id_suffixed:
        return {'status': 'id_suffixed', 'detail': ', '.join(id_suffixed)}

    return {'status': 'ok', 'detail': f'{ini_file.name}, {chart_file.name}'}


def probe_frame_rate(video_path):
    #Variable Frame Rate (VFR) source video causes progressive, cumulative audio/video
    #desync that a single static video_start_time offset cannot fix -- it only corrects
    #the start point, not a drift that grows over the video's duration. r_frame_rate
    #(the stream's nominal/container rate) and avg_frame_rate (the actual average over
    #the whole stream) disagree exactly when the video is VFR; they match for CFR.
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=r_frame_rate,avg_frame_rate',
             '-of', 'json', str(video_path)],
            check=True, capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        streams = data.get('streams', [])
        if not streams:
            return False
        stream = streams[0]
        return stream.get('r_frame_rate', '0/0') != stream.get('avg_frame_rate', '0/0')
    except Exception as e:
        logging.error(f"ffprobe error {video_path}: {e}")
        return False


def probe_video_codec(video_path):
    #Returns the video stream's codec name (e.g. "h264", "vp8", "vp9"), or None if
    #ffprobe fails or no video stream is found. Used to catch WebM files encoded with
    #VP9 -- YouTube's default for "bestvideo[ext=webm]" on virtually all current
    #uploads -- which this Clone Hero build cannot decode at all (confirmed via a real
    #playtest: "Unsupported video codec 'VP9'", video never renders). Only VP8 is safe.
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name',
             '-of', 'json', str(video_path)],
            check=True, capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        streams = data.get('streams', [])
        if not streams:
            return None
        return streams[0].get('codec_name')
    except Exception as e:
        logging.error(f"ffprobe codec probe error {video_path}: {e}")
        return None


def reencode_to_cfr(video_path, fps=30):
    #Overwrites video_path in place with a constant-frame-rate re-encode, no backup kept
    #(confirmed decision -- keeps disk usage flat for a 5,000+ song library). Writes to a
    #temp file in the same directory first so a crash mid-encode can't leave a partial/
    #corrupt file at the real path.
    video_path = Path(video_path)
    fd, tmp_path = tempfile.mkstemp(dir=str(video_path.parent), suffix=video_path.suffix)
    os.close(fd)
    try:
        subprocess.run(
            ['ffmpeg', '-nostdin', '-i', str(video_path), '-r', str(fps), '-y', tmp_path],
            check=True, capture_output=True, stdin=subprocess.DEVNULL,
        )
        os.replace(tmp_path, str(video_path))
        return True
    except Exception as e:
        logging.error(f"CFR re-encode error {video_path}: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False


def extract_audio(video_path, out_wav):
    try:
        subprocess.run(['ffmpeg', '-nostdin', '-i', str(video_path), '-vn', '-ar', '16000', '-ac', '1', '-y', str(out_wav)],
                        check=True, capture_output=True, stdin=subprocess.DEVNULL)
        return True
    except Exception as e:
        logging.error(f"FFmpeg error {video_path}: {e}")
        return False

def compute_offset(song_path, vid_audio):
    try:
        result = find_offset_between_files(str(song_path), str(vid_audio))
        #find_offset_between_files' own docstring claims a positive time_offset means
        #"file2 starts after file1" -- empirically verified during implementation that
        #its actual behavior is the opposite (a controlled test: delaying file2's content
        #by a known +0.25s produced time_offset=-0.248, not +0.248). Negating it here
        #converts to Clone Hero's video_start_time convention: positive = skip ahead
        #into the video (it has an intro before the song starts), negative = delay the
        #video's appearance (the video is missing its intro).
        offset_ms = round(-result["time_offset"] * 1000)
        confidence_ratio = result["standard_score"]

        if confidence_ratio < MIN_STANDARD_SCORE:
            return {"offset_ms": offset_ms, "confidence_ratio": confidence_ratio, "status": "low_confidence"}
        return {"offset_ms": offset_ms, "confidence_ratio": confidence_ratio, "status": "ok"}
    except Exception as e:
        logging.error(f"Offset error {song_path}: {e}")
        return {"offset_ms": 0, "confidence_ratio": 0.0, "status": "error"}

