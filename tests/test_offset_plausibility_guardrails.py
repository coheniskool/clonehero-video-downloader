"""Offset-magnitude sanity check + edition-marker detection.

Real-world evidence (2026-07-14): three Test-library songs computed offsets
of -145632ms/-306032ms/-153840ms against song lengths of 207619/338000/206600ms
-- 60-90% of the song's own length, with confidence scores (3.3-6.2) that
otherwise clear the acceptance threshold. Recomputing from scratch against
fresh copies produced byte-identical results, so this isn't noise -- it's a
deterministic but wrong alignment. Two of the three bad videos were labeled
"4K Film Restored" / "2024 Remaster" -- a different cut/timing than what the
chart's own backing track was built against, which a simple linear
time-shift can't reconcile.

These two guardrails don't fix the underlying cross-correlation limitation,
but they stop a confidently-wrong result from being silently written.
"""

import importlib.util
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'CH-VideoScript.py'

_spec = importlib.util.spec_from_file_location('ch_video_script_plausibility_test', MODULE_PATH)
CH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CH)


# --- is_offset_magnitude_plausible -------------------------------------------

def test_rejects_the_real_helena_case():
	assert CH.is_offset_magnitude_plausible(-145632, 207619) is False


def test_rejects_the_real_snow_hey_oh_case():
	assert CH.is_offset_magnitude_plausible(-306032, 338000) is False


def test_rejects_the_real_my_name_is_jonas_case():
	assert CH.is_offset_magnitude_plausible(-153840, 206600) is False


def test_accepts_the_real_kryptonite_case():
	assert CH.is_offset_magnitude_plausible(-96, 240389) is True


def test_accepts_the_real_i_write_sins_case():
	assert CH.is_offset_magnitude_plausible(-15264, 190588) is True


def test_accepts_a_small_positive_offset():
	assert CH.is_offset_magnitude_plausible(1500, 200000) is True


def test_boundary_exactly_at_the_threshold_is_plausible():
	assert CH.is_offset_magnitude_plausible(60000, 200000) is True  # exactly 30%


def test_boundary_just_over_the_threshold_is_implausible():
	assert CH.is_offset_magnitude_plausible(60001, 200000) is False


def test_never_blocks_when_song_length_is_missing():
	# no song_length to sanity-check against -- don't block on missing data
	assert CH.is_offset_magnitude_plausible(999999, None) is True
	assert CH.is_offset_magnitude_plausible(999999, 0) is True


# --- detect_edition_marker ----------------------------------------------------

def test_detects_remaster_in_the_real_weezer_title():
	assert CH.detect_edition_marker("Weezer - My Name Is Jonas (2024 Remaster)") == "remaster"


def test_detects_restored_in_the_real_mcr_title():
	assert CH.detect_edition_marker("My Chemical Romance - Helena [Official Music Video - 4K Film Restored]") == "restored"


def test_does_not_flag_a_plain_official_video_title():
	assert CH.detect_edition_marker("3 Doors Down - Kryptonite (Official Video)") is None


def test_does_not_flag_the_real_rhcp_title():
	assert CH.detect_edition_marker("Red Hot Chili Peppers - Snow (Hey Oh) (Official Music Video)") is None


def test_detects_extended_edition():
	assert CH.detect_edition_marker("Some Song (Extended Edition)") == "extended edition"


def test_detects_anniversary_edition():
	assert CH.detect_edition_marker("Some Song (10th Anniversary Edition)") == "10th anniversary edition"


def test_detects_directors_cut():
	assert CH.detect_edition_marker("Some Song (Director's Cut)") is not None


def test_is_case_insensitive():
	assert CH.detect_edition_marker("SOME SONG (REMASTERED)") == "remastered"


def test_returns_none_for_empty_or_none_title():
	assert CH.detect_edition_marker(None) is None
	assert CH.detect_edition_marker("") is None


# --- integration into apply_audio_offset() -----------------------------------

FAKE_RESULT_IMPLAUSIBLE = {"offset_ms": -145632, "confidence_ratio": 3.35, "status": "ok"}
FAKE_RESULT_PLAUSIBLE = {"offset_ms": -96, "confidence_ratio": 2.56, "status": "ok"}


def _make_fixture(tmp_path, song_length=207619):
	(tmp_path / "video.mp4").write_bytes(b"original-video-bytes")
	(tmp_path / "song.ogg").write_bytes(b"fake-audio")
	(tmp_path / "song.ini").write_text(f"[Song]\nvideo_start_time = 0\nsong_length = {song_length}\n", encoding="utf-8")
	return tmp_path


def test_apply_audio_offset_rejects_implausible_magnitude_and_does_not_write(tmp_path):
	_make_fixture(tmp_path, song_length=207619)
	ini_before = (tmp_path / "song.ini").read_text(encoding="utf-8")

	with patch.object(CH, "OFFSET_SUPPORT", True), \
	     patch.object(CH, "probe_frame_rate", return_value=False), \
	     patch.object(CH, "extract_audio", return_value=True), \
	     patch.object(CH, "compute_offset", return_value=FAKE_RESULT_IMPLAUSIBLE):
		result = CH.apply_audio_offset(str(tmp_path))

	assert result is False
	assert (tmp_path / "song.ini").read_text(encoding="utf-8") == ini_before
	meta = CH.load_offset_metadata(str(tmp_path))
	assert meta["status"] == "implausible_magnitude"


def test_apply_audio_offset_writes_plausible_offset_normally(tmp_path):
	_make_fixture(tmp_path, song_length=240389)

	with patch.object(CH, "OFFSET_SUPPORT", True), \
	     patch.object(CH, "probe_frame_rate", return_value=False), \
	     patch.object(CH, "extract_audio", return_value=True), \
	     patch.object(CH, "compute_offset", return_value=FAKE_RESULT_PLAUSIBLE):
		result = CH.apply_audio_offset(str(tmp_path))

	assert result is True
	assert "video_start_time = -96" in (tmp_path / "song.ini").read_text(encoding="utf-8")


def test_apply_audio_offset_rejects_when_edition_flag_present(tmp_path):
	_make_fixture(tmp_path, song_length=240389)
	CH.save_video_metadata(str(tmp_path), confidence=60, url="http://example.com/video", title="Some Song (2024 Remaster)")
	ini_before = (tmp_path / "song.ini").read_text(encoding="utf-8")

	with patch.object(CH, "OFFSET_SUPPORT", True), \
	     patch.object(CH, "probe_frame_rate", return_value=False), \
	     patch.object(CH, "extract_audio", return_value=True), \
	     patch.object(CH, "compute_offset", return_value=FAKE_RESULT_PLAUSIBLE):
		result = CH.apply_audio_offset(str(tmp_path))

	assert result is False
	assert (tmp_path / "song.ini").read_text(encoding="utf-8") == ini_before
	meta = CH.load_offset_metadata(str(tmp_path))
	assert meta["status"] == "edition_mismatch_risk"


def test_apply_audio_offset_writes_normally_when_no_edition_flag(tmp_path):
	_make_fixture(tmp_path, song_length=240389)
	CH.save_video_metadata(str(tmp_path), confidence=60, url="http://example.com/video", title="Some Song (Official Video)")

	with patch.object(CH, "OFFSET_SUPPORT", True), \
	     patch.object(CH, "probe_frame_rate", return_value=False), \
	     patch.object(CH, "extract_audio", return_value=True), \
	     patch.object(CH, "compute_offset", return_value=FAKE_RESULT_PLAUSIBLE):
		result = CH.apply_audio_offset(str(tmp_path))

	assert result is True


# --- save_video_metadata()/load_edition_flag() title persistence -------------

def test_save_video_metadata_persists_title_and_edition_flag(tmp_path):
	CH.save_video_metadata(str(tmp_path), confidence=45, url="http://example.com/v", title="Weezer - My Name Is Jonas (2024 Remaster)")

	assert CH.load_edition_flag(str(tmp_path)) == "remaster"


def test_save_video_metadata_no_edition_flag_for_plain_title(tmp_path):
	CH.save_video_metadata(str(tmp_path), confidence=90, url="http://example.com/v", title="3 Doors Down - Kryptonite (Official Video)")

	assert CH.load_edition_flag(str(tmp_path)) is None


def test_save_video_metadata_backward_compatible_without_title(tmp_path):
	# existing call sites that don't pass title must keep working unchanged
	CH.save_video_metadata(str(tmp_path), confidence=90, url="http://example.com/v")

	assert CH.load_edition_flag(str(tmp_path)) is None


def test_load_edition_flag_none_when_no_metadata_file(tmp_path):
	assert CH.load_edition_flag(str(tmp_path)) is None


def test_download_video_if_needed_threads_title_through_to_metadata(tmp_path):
	with patch.object(CH, "yt_dlp") as mock_yt_dlp:
		mock_ydl = mock_yt_dlp.YoutubeDL.return_value.__enter__.return_value
		mock_ydl.download.return_value = None
		result = CH.download_video_if_needed(
			"http://example.com/v", str(tmp_path), 60, title="Some Song (Remastered)"
		)

	assert result is True
	assert CH.load_edition_flag(str(tmp_path)) == "remastered"
