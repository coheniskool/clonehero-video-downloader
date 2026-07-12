"""Library status report generator (Task 10).

A read-only scan across every song folder under HOME_FOLDER, producing a
single CSV so the ~5,131-song library's video/offset coverage can be
reviewed at a glance: has video? video confidence, has offset? offset
confidence/status, CH-score status (always "unknown" per the Task 9 spike),
and a derived needs_review flag. This is purely a reporting pass over
video_meta.json/song folder contents already written by earlier phases --
it must never write to song.ini, video_meta.json, or any video file.
"""

import csv
import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'CH-VideoScript.py'

_spec = importlib.util.spec_from_file_location('ch_video_script_report_test', MODULE_PATH)
CH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CH)


def _make_song_folder(home, name, video=False, video_confidence=None, offset_status=None, offset_confidence=None, offset_ms=None):
	folder = home / name
	folder.mkdir()
	if video:
		(folder / 'video.mp4').write_bytes(b'fake')
	meta = {}
	if video_confidence is not None:
		meta['confidence'] = video_confidence
		meta['url'] = 'http://example.com/' + name
	if offset_status is not None:
		meta['offset'] = {
			'offset_ms': offset_ms if offset_ms is not None else 0,
			'confidence': offset_confidence if offset_confidence is not None else 0.0,
			'status': offset_status,
			'updated_at': '2026-07-11T00:00:00+00:00',
		}
	if meta:
		(folder / CH.VIDEO_METADATA_FILENAME).write_text(json.dumps(meta), encoding='utf-8')
	return folder


def _read_report_rows(report_path):
	with open(report_path, newline='', encoding='utf-8') as f:
		return list(csv.DictReader(f))


def test_generates_one_row_per_song_folder(tmp_path):
	_make_song_folder(tmp_path, 'Artist A - Song A', video=True, video_confidence=95, offset_status='written', offset_confidence=9.0, offset_ms=100)
	_make_song_folder(tmp_path, 'Artist B - Song B', video=True, video_confidence=95, offset_status='written', offset_confidence=9.0, offset_ms=200)

	report_path = CH.generate_library_report(str(tmp_path))

	rows = _read_report_rows(report_path)
	assert len(rows) == 2
	assert {r['folder'] for r in rows} == {'Artist A - Song A', 'Artist B - Song B'}


def test_flags_needs_review_when_no_video(tmp_path):
	_make_song_folder(tmp_path, 'Artist - Song', video=False)

	report_path = CH.generate_library_report(str(tmp_path))

	row = _read_report_rows(report_path)[0]
	assert row['has_video'] == 'False'
	assert row['needs_review'] == 'True'


def test_flags_needs_review_when_low_video_confidence(tmp_path):
	_make_song_folder(tmp_path, 'Artist - Song', video=True, video_confidence=40)

	report_path = CH.generate_library_report(str(tmp_path))

	row = _read_report_rows(report_path)[0]
	assert row['needs_review'] == 'True'


def test_flags_needs_review_when_offset_not_written(tmp_path):
	_make_song_folder(tmp_path, 'Artist - Song', video=True, video_confidence=95, offset_status='low_confidence', offset_confidence=0.2)

	report_path = CH.generate_library_report(str(tmp_path))

	row = _read_report_rows(report_path)[0]
	assert row['needs_review'] == 'True'


def test_no_review_flag_when_fully_confirmed(tmp_path):
	_make_song_folder(tmp_path, 'Artist - Song', video=True, video_confidence=95, offset_status='written', offset_confidence=9.0, offset_ms=150)

	report_path = CH.generate_library_report(str(tmp_path))

	row = _read_report_rows(report_path)[0]
	assert row['needs_review'] == 'False'
	assert row['offset_ms'] == '150'


def test_ch_score_status_is_always_unknown(tmp_path):
	_make_song_folder(tmp_path, 'Artist - Song', video=True, video_confidence=95, offset_status='written', offset_confidence=9.0)

	report_path = CH.generate_library_report(str(tmp_path))

	row = _read_report_rows(report_path)[0]
	assert row['ch_score_status'] == 'unknown'


def test_report_generation_is_read_only(tmp_path):
	folder = _make_song_folder(tmp_path, 'Artist - Song', video=True, video_confidence=95, offset_status='written', offset_confidence=9.0)
	video_before = (folder / 'video.mp4').read_bytes()
	meta_before = (folder / CH.VIDEO_METADATA_FILENAME).read_text(encoding='utf-8')

	CH.generate_library_report(str(tmp_path))

	assert (folder / 'video.mp4').read_bytes() == video_before
	assert (folder / CH.VIDEO_METADATA_FILENAME).read_text(encoding='utf-8') == meta_before


def test_write_failure_leaves_no_stray_temp_file(tmp_path, monkeypatch):
	_make_song_folder(tmp_path, 'Artist - Song', video=True, video_confidence=95, offset_status='written', offset_confidence=9.0)

	import os as os_module
	real_replace = os_module.replace

	def boom(*args, **kwargs):
		raise OSError("simulated failure")

	monkeypatch.setattr(CH.os, "replace", boom)

	try:
		CH.generate_library_report(str(tmp_path))
	except OSError:
		pass

	stray_files = [p for p in tmp_path.iterdir() if p.is_file() and p.suffix == '.csv']
	assert stray_files == []
