"""compute_offset() sourced from audio-offset-finder instead of librosa/DTW.

Fast, mocked-backend tests proving the new implementation's contract: same
{offset_ms, confidence_ratio, status} dict shape the callers already branch
on, the empirically-verified sign negation (audio-offset-finder's own
time_offset sign is the opposite of what its docstring claims), and correct
status branching. The full unmocked, ffmpeg-based proof of the sign
convention lives in test_compute_offset_sign.py (the Task 6 gate) -- these
tests are the fast unit-level lock-in of the same contract.
"""

from unittest.mock import patch

import clonehero_video_offset as module


def _fake_result(time_offset, standard_score):
	return {
		"time_offset": time_offset,
		"frame_offset": 0,
		"standard_score": standard_score,
		"correlation": None,
		"time_scale": 1.0,
		"earliest_frame_offset": -100,
		"latest_frame_offset": 100,
	}


def test_negates_raw_time_offset_to_match_video_start_time_convention():
	# audio-offset-finder's own docstring claims a positive time_offset means
	# "file2 starts after file1" -- empirically verified (see Task 5 commit)
	# that its actual behavior is the opposite. -2.5s raw here must become
	# +2500ms, matching Clone Hero's video_start_time sign (positive = skip
	# ahead into the video, used when the video has an intro before the song).
	with patch.object(module, "find_offset_between_files", return_value=_fake_result(-2.5, 9.0)):
		result = module.compute_offset("song.ogg", "vid_audio.wav")

	assert result["offset_ms"] == 2500
	assert result["status"] == "ok"


def test_positive_raw_time_offset_becomes_negative_video_start_time():
	with patch.object(module, "find_offset_between_files", return_value=_fake_result(1.2, 9.0)):
		result = module.compute_offset("song.ogg", "vid_audio.wav")

	assert result["offset_ms"] == -1200


def test_low_confidence_status_when_standard_score_below_threshold():
	with patch.object(module, "find_offset_between_files", return_value=_fake_result(0.1, 0.05)):
		result = module.compute_offset("song.ogg", "vid_audio.wav")

	assert result["status"] == "low_confidence"
	assert result["confidence_ratio"] == 0.05


def test_error_status_on_exception():
	with patch.object(module, "find_offset_between_files", side_effect=RuntimeError("boom")):
		result = module.compute_offset("song.ogg", "vid_audio.wav")

	assert result["status"] == "error"
	assert result["offset_ms"] == 0
	assert result["confidence_ratio"] == 0.0


def test_returns_expected_dict_shape():
	with patch.object(module, "find_offset_between_files", return_value=_fake_result(0.5, 9.0)):
		result = module.compute_offset("song.ogg", "vid_audio.wav")

	assert set(result.keys()) == {"offset_ms", "confidence_ratio", "status"}
