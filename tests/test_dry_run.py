"""--dry-run wired end-to-end through apply_audio_offset() (Task 11).

With dry_run=True, apply_audio_offset() must still run VFR detection,
extraction, and compute_offset() (so the user sees what WOULD happen), but
must never write to song.ini, overwrite the video file, or persist to
video_meta.json. Without it, all three still happen as before.
"""

import importlib.util
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'CH-VideoScript.py'

_spec = importlib.util.spec_from_file_location('ch_video_script_dry_run_test', MODULE_PATH)
CH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CH)

FAKE_RESULT = {"offset_ms": 4200, "confidence_ratio": 9.0, "status": "ok"}


def _make_fixture(tmp_path):
	(tmp_path / "video.mp4").write_bytes(b"original-video-bytes")
	(tmp_path / "song.ogg").write_bytes(b"fake-audio")
	(tmp_path / "song.ini").write_text("[Song]\nvideo_start_time = 0\n", encoding="utf-8")
	return tmp_path


def test_dry_run_leaves_song_ini_video_and_metadata_untouched(tmp_path):
	_make_fixture(tmp_path)
	video_before = (tmp_path / "video.mp4").read_bytes()
	ini_before = (tmp_path / "song.ini").read_text(encoding="utf-8")

	with patch.object(CH, "OFFSET_SUPPORT", True), \
	     patch.object(CH, "probe_frame_rate", return_value=False), \
	     patch.object(CH, "extract_audio", return_value=True), \
	     patch.object(CH, "compute_offset", return_value=FAKE_RESULT):
		result = CH.apply_audio_offset(str(tmp_path), dry_run=True)

	assert result is False
	assert (tmp_path / "video.mp4").read_bytes() == video_before
	assert (tmp_path / "song.ini").read_text(encoding="utf-8") == ini_before
	assert not (tmp_path / CH.VIDEO_METADATA_FILENAME).exists()


def test_without_dry_run_writes_song_ini_and_metadata(tmp_path):
	_make_fixture(tmp_path)

	with patch.object(CH, "OFFSET_SUPPORT", True), \
	     patch.object(CH, "probe_frame_rate", return_value=False), \
	     patch.object(CH, "extract_audio", return_value=True), \
	     patch.object(CH, "compute_offset", return_value=FAKE_RESULT):
		result = CH.apply_audio_offset(str(tmp_path), dry_run=False)

	assert result is True
	assert "video_start_time = 4200" in (tmp_path / "song.ini").read_text(encoding="utf-8")
	assert (tmp_path / CH.VIDEO_METADATA_FILENAME).exists()


def test_dry_run_does_not_reencode_vfr_video(tmp_path):
	_make_fixture(tmp_path)
	video_before = (tmp_path / "video.mp4").read_bytes()

	with patch.object(CH, "OFFSET_SUPPORT", True), \
	     patch.object(CH, "probe_frame_rate", return_value=True), \
	     patch.object(CH, "reencode_to_cfr") as mock_reencode, \
	     patch.object(CH, "extract_audio", return_value=True), \
	     patch.object(CH, "compute_offset", return_value=FAKE_RESULT):
		CH.apply_audio_offset(str(tmp_path), dry_run=True)

	mock_reencode.assert_not_called()
	assert (tmp_path / "video.mp4").read_bytes() == video_before
