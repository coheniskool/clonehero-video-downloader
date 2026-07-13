""".chart embedded Name/Artist fuzzy-match against song.ini, >=85 threshold.

Both Name AND Artist must independently clear the threshold -- the real
Mr. Roboto case (found 2026-07-12 triage) has a matching Artist ("Styx") but
a completely wrong Name ("Rock & Roll Feeling" vs. the folder's "Mr. Roboto"),
so an OR-based check would have wrongly passed it. verify_chart_content_match()
must relocate this case to needs_review, never rename.
"""

import clonehero_video_offset as module


def _write_chart(path, name, artist):
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		'﻿[Song]\n{\n  Name = "%s"\n  Artist = "%s"\n  Offset = 0\n}\n' % (name, artist),
		encoding="utf-8",
	)


def test_matches_when_name_and_artist_are_identical(tmp_path):
	_write_chart(tmp_path / "notes_454.chart", "Mr. Roboto", "Styx")

	matched, reason = module.verify_chart_content_match(tmp_path, {"name": "Mr. Roboto", "artist": "Styx"})

	assert matched is True


def test_matches_with_minor_formatting_differences(tmp_path):
	# real charts commonly differ in punctuation/spacing from the folder's song.ini
	_write_chart(tmp_path / "notes_454.chart", "Mr Roboto", "Styx")

	matched, reason = module.verify_chart_content_match(tmp_path, {"name": "Mr. Roboto", "artist": "Styx"})

	assert matched is True


def test_rejects_real_mr_roboto_case_matching_artist_wrong_name(tmp_path):
	# the actual real-library case: Artist matches, Name is a completely different song
	_write_chart(tmp_path / "notes_454.chart", "Rock & Roll Feeling", "Styx")

	matched, reason = module.verify_chart_content_match(tmp_path, {"name": "Mr. Roboto", "artist": "Styx"})

	assert matched is False
	assert "name" in reason.lower()


def test_rejects_when_artist_does_not_match_even_if_name_does(tmp_path):
	_write_chart(tmp_path / "notes_454.chart", "Mr. Roboto", "Some Other Band")

	matched, reason = module.verify_chart_content_match(tmp_path, {"name": "Mr. Roboto", "artist": "Styx"})

	assert matched is False
	assert "artist" in reason.lower()


def test_rejects_when_both_name_and_artist_differ(tmp_path):
	_write_chart(tmp_path / "notes_454.chart", "Totally Different Song", "Totally Different Band")

	matched, reason = module.verify_chart_content_match(tmp_path, {"name": "Mr. Roboto", "artist": "Styx"})

	assert matched is False


def test_no_chart_or_mid_file_present_returns_false_never_raises(tmp_path):
	matched, reason = module.verify_chart_content_match(tmp_path, {"name": "Mr. Roboto", "artist": "Styx"})

	assert matched is False
