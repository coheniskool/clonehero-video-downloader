"""scan_song_folder_video()'s VP9 rejection.

A real playtest confirmed this Clone Hero build throws "Unsupported video
codec 'VP9'" and never renders the video at all. The download format string
was fixed to prefer MP4, but any *existing* WebM file (already downloaded
before that fix, or ever renamed into place by this repair scan without a
codec check) would previously be silently accepted as "ok" forever --
has_existing_video() would then always see a video present and skip any
future re-download, leaving it permanently broken. The repair scan must
reject non-VP8 WebM files so they become eligible for a fresh MP4 download.
"""

import importlib.util
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'CH-VideoScript.py'

_spec = importlib.util.spec_from_file_location('ch_video_script_codec_scan_test', MODULE_PATH)
CH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CH)


def test_removes_canonical_webm_with_vp9_codec(tmp_path):
	(tmp_path / 'video.webm').write_bytes(b'fake-vp9-video')

	with patch.object(CH, 'OFFSET_SUPPORT', True), patch.object(CH, 'probe_video_codec', return_value='vp9'):
		result = CH.scan_song_folder_video(tmp_path)

	assert result['status'] == 'unsupported_codec'
	assert not (tmp_path / 'video.webm').exists()


def test_keeps_canonical_webm_with_vp8_codec(tmp_path):
	(tmp_path / 'video.webm').write_bytes(b'fake-vp8-video')

	with patch.object(CH, 'OFFSET_SUPPORT', True), patch.object(CH, 'probe_video_codec', return_value='vp8'):
		result = CH.scan_song_folder_video(tmp_path)

	assert result['status'] == 'ok'
	assert (tmp_path / 'video.webm').exists()


def test_removes_renamed_webm_with_vp9_codec(tmp_path):
	(tmp_path / 'video.someid.webm').write_bytes(b'fake-vp9-video')

	with patch.object(CH, 'OFFSET_SUPPORT', True), patch.object(CH, 'probe_video_codec', return_value='vp9'):
		result = CH.scan_song_folder_video(tmp_path)

	assert result['status'] == 'unsupported_codec'
	assert not (tmp_path / 'video.webm').exists()
	assert not (tmp_path / 'video.someid.webm').exists()


def test_renames_webm_with_vp8_codec_as_before(tmp_path):
	(tmp_path / 'video.someid.webm').write_bytes(b'fake-vp8-video')

	with patch.object(CH, 'OFFSET_SUPPORT', True), patch.object(CH, 'probe_video_codec', return_value='vp8'):
		result = CH.scan_song_folder_video(tmp_path)

	assert result['status'] == 'fixed_rename'
	assert (tmp_path / 'video.webm').exists()


def test_skips_codec_check_when_offset_support_unavailable(tmp_path):
	# graceful degradation, matching the rest of the codebase's pattern: if the
	# offset module (and thus ffprobe-wrapping helpers) isn't importable, don't
	# block the existing rename/accept behavior on a check we can't perform
	(tmp_path / 'video.webm').write_bytes(b'fake-video')

	with patch.object(CH, 'OFFSET_SUPPORT', False):
		result = CH.scan_song_folder_video(tmp_path)

	assert result['status'] == 'ok'
	assert (tmp_path / 'video.webm').exists()


def test_mp4_files_are_never_codec_checked(tmp_path):
	(tmp_path / 'video.mp4').write_bytes(b'fake-mp4-video')

	with patch.object(CH, 'OFFSET_SUPPORT', True), patch.object(CH, 'probe_video_codec') as mock_probe:
		result = CH.scan_song_folder_video(tmp_path)

	mock_probe.assert_not_called()
	assert result['status'] == 'ok'
