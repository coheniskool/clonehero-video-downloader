"""Sign-convention gate for compute_offset() -- do not skip, do not weaken.

Every song.ini write in this feature depends on compute_offset()'s sign being
correct. It has never been verified end-to-end against a real, ffmpeg-produced
audio delay (as opposed to the mocked-backend tests in
test_compute_offset_backend.py, which only prove the negation math given an
assumed raw time_offset). This test builds a synthetic reference clip and a
copy with a real, known injected delay via ffmpeg's adelay filter, then
asserts compute_offset()'s sign and magnitude match.

Note: ffmpeg's -itsoffset flag (suggested in the original spec) does NOT
actually pad silence into a raw WAV with -c copy -- verified empirically
during implementation (frame count is unchanged). The adelay audio filter is
what actually inserts real silence samples, so that's what's used here.
"""

import shutil
import subprocess
import wave

import numpy as np
import pytest

import clonehero_video_offset as module

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None

SAMPLE_RATE = 16000
DURATION_S = 5.0
INJECTED_DELAY_MS = 300
TOLERANCE_MS = 30


def _make_reference_clip(path):
	t = np.linspace(0, DURATION_S, int(SAMPLE_RATE * DURATION_S), endpoint=False)
	rng = np.random.default_rng(12345)
	# a percussive-ish, non-repeating signal so the correlation peak is unambiguous
	sig = np.sin(2 * np.pi * 440 * t) * np.exp(-3 * (t % 1.0)) + 0.05 * rng.standard_normal(len(t))
	sig = (sig / np.max(np.abs(sig)) * 0.8 * 32767).astype(np.int16)
	with wave.open(str(path), "wb") as f:
		f.setnchannels(1)
		f.setsampwidth(2)
		f.setframerate(SAMPLE_RATE)
		f.writeframes(sig.tobytes())


def _delay_clip(src_path, dst_path, delay_ms):
	subprocess.run(
		["ffmpeg", "-y", "-nostdin", "-i", str(src_path), "-af", "adelay={}:all=1".format(delay_ms), str(dst_path)],
		check=True, capture_output=True,
	)


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg not on PATH")
def test_video_audio_delayed_relative_to_song_gives_positive_offset(tmp_path):
	# video's matching content starts LATER than the song's (e.g. the video has an
	# intro before the song kicks in) -- Clone Hero must skip ahead into the video,
	# so video_start_time must come back positive.
	song = tmp_path / "song.wav"
	video_audio = tmp_path / "video_audio.wav"
	_make_reference_clip(song)
	_delay_clip(song, video_audio, INJECTED_DELAY_MS)

	result = module.compute_offset(song, video_audio)

	assert result["status"] == "ok"
	assert abs(result["offset_ms"] - INJECTED_DELAY_MS) <= TOLERANCE_MS, (
		"expected offset_ms near +{}, got {}".format(INJECTED_DELAY_MS, result["offset_ms"])
	)


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg not on PATH")
def test_song_audio_delayed_relative_to_video_gives_negative_offset(tmp_path):
	# song's reference audio starts LATER than the video's matching content (e.g.
	# the video is missing its intro) -- Clone Hero must delay the video's on-screen
	# appearance, so video_start_time must come back negative.
	video_audio = tmp_path / "video_audio.wav"
	song = tmp_path / "song.wav"
	_make_reference_clip(video_audio)
	_delay_clip(video_audio, song, INJECTED_DELAY_MS)

	result = module.compute_offset(song, video_audio)

	assert result["status"] == "ok"
	assert abs(result["offset_ms"] - (-INJECTED_DELAY_MS)) <= TOLERANCE_MS, (
		"expected offset_ms near -{}, got {}".format(INJECTED_DELAY_MS, result["offset_ms"])
	)
