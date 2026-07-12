# clonehero_video_offset.py
# pip install librosa numpy

import subprocess
from pathlib import Path
import librosa
import numpy as np
import logging
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler('clonehero_offset.log', maxBytes=1_000_000, backupCount=5)
logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s - %(levelname)s - %(message)s')

#Analysis window in seconds. Offsets larger than this can never be measured,
#since only the first WINDOW_S seconds of each track are loaded.
WINDOW_S = 45
#Detected offsets beyond this are untrustworthy noise from window-edge effects
#rather than genuine large intros -- flagged and skipped instead of clamped.
#Scaled off WINDOW_S: an offset near the full window means the true offset
#may be even larger and we simply can't tell, but one comfortably inside it
#(e.g. a 27s intro within a 45s window) is a legitimate measurement.
MAX_TRUSTED_OFFSET_MS = int(WINDOW_S * 1000 * 0.75)
#Ratio of (90th-10th percentile spread) to (min cost) in the DTW path's final
#row. Low ratio means the cost landscape is flat/noisy -- no real alignment
#signal -- and the backtrack just defaults to a trivial near-zero-shift path.
MIN_CONFIDENCE_RATIO = 0.3

#Clone Hero's own convention for the full mixed track. Multitrack charts also
#ship isolated stems (drums.ogg, crowd.ogg, vocals.ogg, ...) that must NOT be
#used as the alignment reference -- their onset pattern doesn't correspond to
#the video's full mix at all.
FULL_MIX_NAMES = ('song.ogg', 'song.opus', 'song.mp3', 'song.wav')
#Only Clone Hero's officially recognized background-video filenames.
VIDEO_NAMES = ('video.mp4', 'video.avi', 'video.webm', 'video.ogv')


def find_song_audio(song_dir):
    for name in FULL_MIX_NAMES:
        candidate = song_dir / name
        if candidate.exists():
            return candidate
    #No dedicated full-mix file -- only safe to use a stem if it's the only track present.
    audio_files = [f for f in song_dir.glob('*') if f.suffix.lower() in {'.ogg', '.mp3', '.wav', '.opus'}]
    return audio_files[0] if len(audio_files) == 1 else None


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

def compute_offset(song_path, vid_audio, sr=16000, hop_length=1024):
    try:
        y_song, _ = librosa.load(song_path, sr=sr, duration=WINDOW_S)
        y_vid, _ = librosa.load(vid_audio, sr=sr, duration=WINDOW_S)
        oenv_song = librosa.onset.onset_strength(y=y_song, sr=sr, hop_length=hop_length)
        oenv_vid = librosa.onset.onset_strength(y=y_vid, sr=sr, hop_length=hop_length)
        D, wp = librosa.sequence.dtw(oenv_song, oenv_vid, subseq=True, metric='euclidean')
        offset_frames = wp[-1, 0] - wp[-1, 1]
        offset_ms = int(offset_frames * hop_length / sr * 1000)

        last_row = D[-1, :]
        min_cost = float(last_row.min())
        spread = float(np.percentile(last_row, 90) - np.percentile(last_row, 10))
        confidence_ratio = spread / min_cost if min_cost > 0 else 0.0

        if abs(offset_ms) > MAX_TRUSTED_OFFSET_MS:
            return {"offset_ms": offset_ms, "confidence_ratio": confidence_ratio, "status": "exceeds_window"}
        if confidence_ratio < MIN_CONFIDENCE_RATIO:
            return {"offset_ms": offset_ms, "confidence_ratio": confidence_ratio, "status": "low_confidence"}
        return {"offset_ms": offset_ms, "confidence_ratio": confidence_ratio, "status": "ok"}
    except Exception as e:
        logging.error(f"Offset error {song_path}: {e}")
        return {"offset_ms": 0, "confidence_ratio": 0.0, "status": "error"}

