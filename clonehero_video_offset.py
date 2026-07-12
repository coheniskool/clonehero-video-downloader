# clonehero_video_offset.py
# pip install audio-offset-finder numpy
# NOTE: numpy must land in the >=2,<=2.4 window on this environment -- numpy 1.26.x
# breaks scipy's C extensions on Python 3.14, and numpy 2.5+ breaks numba (a librosa
# dependency, which audio-offset-finder itself uses internally for MFCC computation).

import subprocess
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

