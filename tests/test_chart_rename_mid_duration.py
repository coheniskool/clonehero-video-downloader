""".mid duration-vs-song_length fallback, +/-2000ms tolerance.

notes.mid carries no embedded human-readable song-name text chunk (unlike
.chart's [Song] Name/Artist), so verification falls back to comparing the
paired audio file's real duration (via ffprobe) against song.ini's
song_length. ffprobe itself is mocked here -- validated for real via
--dry-run against the real library, matching this project's existing
VFR-probe testing philosophy.
"""

from unittest.mock import MagicMock, patch

import clonehero_video_offset as module


def _fake_completed_process(stdout):
	proc = MagicMock()
	proc.stdout = stdout
	return proc


def _touch(path):
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_bytes(b"")


DURATION_JSON_240s = '{"format": {"duration": "240.389000"}}'
DURATION_JSON_241s = '{"format": {"duration": "241.500000"}}'  # within +/-2000ms of 240389ms
DURATION_JSON_250s = '{"format": {"duration": "250.000000"}}'  # ~9.6s off, outside tolerance
NO_FORMAT_JSON = '{}'


def test_matches_when_duration_within_tolerance(tmp_path):
	_touch(tmp_path / "notes_232.mid")
	_touch(tmp_path / "song_1877.ogg")

	with patch.object(module.subprocess, "run", return_value=_fake_completed_process(DURATION_JSON_241s)):
		matched, reason = module.verify_chart_content_match(tmp_path, {"song_length": "240389"})

	assert matched is True


def test_matches_when_duration_is_exact(tmp_path):
	_touch(tmp_path / "notes_232.mid")
	_touch(tmp_path / "song_1877.ogg")

	with patch.object(module.subprocess, "run", return_value=_fake_completed_process(DURATION_JSON_240s)):
		matched, reason = module.verify_chart_content_match(tmp_path, {"song_length": "240389"})

	assert matched is True


def test_rejects_when_duration_outside_tolerance(tmp_path):
	_touch(tmp_path / "notes_232.mid")
	_touch(tmp_path / "song_1877.ogg")

	with patch.object(module.subprocess, "run", return_value=_fake_completed_process(DURATION_JSON_250s)):
		matched, reason = module.verify_chart_content_match(tmp_path, {"song_length": "240389"})

	assert matched is False
	assert "duration" in reason.lower()


def test_rejects_when_no_audio_file_to_probe(tmp_path):
	_touch(tmp_path / "notes_232.mid")
	# no audio file present at all

	matched, reason = module.verify_chart_content_match(tmp_path, {"song_length": "240389"})

	assert matched is False


def test_rejects_when_ffprobe_reports_no_duration(tmp_path):
	_touch(tmp_path / "notes_232.mid")
	_touch(tmp_path / "song_1877.ogg")

	with patch.object(module.subprocess, "run", return_value=_fake_completed_process(NO_FORMAT_JSON)):
		matched, reason = module.verify_chart_content_match(tmp_path, {"song_length": "240389"})

	assert matched is False


def test_rejects_when_ffprobe_fails_never_raises(tmp_path):
	_touch(tmp_path / "notes_232.mid")
	_touch(tmp_path / "song_1877.ogg")

	with patch.object(module.subprocess, "run", side_effect=OSError("ffprobe not found")):
		matched, reason = module.verify_chart_content_match(tmp_path, {"song_length": "240389"})

	assert matched is False


def test_rejects_when_song_ini_has_no_song_length(tmp_path):
	_touch(tmp_path / "notes_232.mid")
	_touch(tmp_path / "song_1877.ogg")

	with patch.object(module.subprocess, "run", return_value=_fake_completed_process(DURATION_JSON_240s)):
		matched, reason = module.verify_chart_content_match(tmp_path, {})

	assert matched is False
