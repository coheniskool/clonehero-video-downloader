"""video_meta.json offset fields + resumability.

Extends the existing per-folder video_meta.json (already used for video-match
confidence) with offset_ms/offset_confidence/offset_status/updated_at, and
gates apply_audio_offset() to skip folders whose offset attempt already
reached a settled status. Without this, a rerun over the ~5,131-song library
recomputes every offset from scratch every time.
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'CH-VideoScript.py'

_spec = importlib.util.spec_from_file_location('ch_video_script_resumability_test', MODULE_PATH)
CH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CH)


def _read_meta(song_folder):
	return json.loads((Path(song_folder) / CH.VIDEO_METADATA_FILENAME).read_text(encoding='utf-8'))


def test_save_offset_metadata_creates_file_with_offset_fields(tmp_path):
	CH.save_offset_metadata(str(tmp_path), offset_ms=1234, confidence=8.5, status='written')

	meta = _read_meta(tmp_path)
	assert meta['offset']['offset_ms'] == 1234
	assert meta['offset']['confidence'] == 8.5
	assert meta['offset']['status'] == 'written'
	assert 'updated_at' in meta['offset']


def test_save_offset_metadata_preserves_existing_video_confidence_fields(tmp_path):
	(tmp_path / CH.VIDEO_METADATA_FILENAME).write_text(
		json.dumps({'confidence': 90, 'url': 'http://example.com/video'}), encoding='utf-8'
	)

	CH.save_offset_metadata(str(tmp_path), offset_ms=500, confidence=9.1, status='written')

	meta = _read_meta(tmp_path)
	assert meta['confidence'] == 90
	assert meta['url'] == 'http://example.com/video'
	assert meta['offset']['offset_ms'] == 500


@pytest.mark.parametrize('status', ['written', 'low_confidence', 'no_reference_audio', 'vfr_exceeds_window'])
def test_is_offset_settled_true_for_terminal_statuses(tmp_path, status):
	CH.save_offset_metadata(str(tmp_path), offset_ms=0, confidence=0.0, status=status)

	assert CH.is_offset_settled(str(tmp_path)) is True


def test_is_offset_settled_false_for_error_status(tmp_path):
	CH.save_offset_metadata(str(tmp_path), offset_ms=0, confidence=0.0, status='error')

	assert CH.is_offset_settled(str(tmp_path)) is False


def test_is_offset_settled_false_when_no_metadata_file(tmp_path):
	assert CH.is_offset_settled(str(tmp_path)) is False


def test_is_offset_settled_false_when_metadata_has_no_offset_key(tmp_path):
	(tmp_path / CH.VIDEO_METADATA_FILENAME).write_text(json.dumps({'confidence': 90}), encoding='utf-8')

	assert CH.is_offset_settled(str(tmp_path)) is False


def test_apply_audio_offset_skips_recomputation_when_already_settled(tmp_path):
	(tmp_path / 'video.mp4').write_bytes(b'fake')
	(tmp_path / 'song.ogg').write_bytes(b'fake')
	CH.save_offset_metadata(str(tmp_path), offset_ms=1234, confidence=8.5, status='written')

	with patch.object(CH, 'compute_offset') as mock_compute, patch.object(CH, 'OFFSET_SUPPORT', True):
		result = CH.apply_audio_offset(str(tmp_path))

	mock_compute.assert_not_called()
	assert result is False


def test_save_offset_metadata_defaults_source_to_computed(tmp_path):
	CH.save_offset_metadata(str(tmp_path), offset_ms=1234, confidence=8.5, status='written')

	meta = _read_meta(tmp_path)
	assert meta['offset']['source'] == 'computed'


def test_save_offset_metadata_records_spreadsheet_source(tmp_path):
	CH.save_offset_metadata(str(tmp_path), offset_ms=-2700, confidence=None, status='written', source='spreadsheet')

	meta = _read_meta(tmp_path)
	assert meta['offset']['source'] == 'spreadsheet'
	assert meta['offset']['offset_ms'] == -2700


def test_spreadsheet_sourced_offset_is_settled_and_skips_audio_detection(tmp_path):
	# a spreadsheet-sourced offset is "written" just like a computed one, so it must
	# be recognized as settled -- this is what makes a spreadsheet entry "run once"
	(tmp_path / 'video.mp4').write_bytes(b'fake')
	(tmp_path / 'song.ogg').write_bytes(b'fake')
	CH.save_offset_metadata(str(tmp_path), offset_ms=-2700, confidence=None, status='written', source='spreadsheet')

	assert CH.is_offset_settled(str(tmp_path)) is True

	with patch.object(CH, 'compute_offset') as mock_compute, patch.object(CH, 'OFFSET_SUPPORT', True):
		result = CH.apply_audio_offset(str(tmp_path))

	mock_compute.assert_not_called()
	assert result is False
