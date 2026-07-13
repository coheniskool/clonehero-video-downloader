"""move_to_duplicates_review(): same-volume/cross-volume-aware relocation
+ manifest, mirroring clonehero_video_offset.py's move_to_needs_review()
for cross-feature consistency.

Resumability is implicit, not a separate state file: once a loser is moved
out of the library root, it simply won't appear in the next run's folder
scan, so group_candidates() naturally stops finding it as a duplicate.

A cross-volume move must verify the destination is complete before
removing the source -- an interrupted copy is real, permanent data loss on
an irreplaceable library.
"""

import json
from unittest.mock import patch

import dedupe_report as module


def _touch(path):
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_bytes(b"")


def _make_song_folder(home, name):
	folder = home / name
	_touch(folder / "song.ini")
	_touch(folder / "notes.chart")
	return folder


def test_same_volume_move_relocates_folder_intact(tmp_path):
	home = tmp_path / "library"
	home.mkdir()
	folder = _make_song_folder(home, "Weezer - My Name Is Jonas [dup2]")

	dest = module.move_to_duplicates_review(folder, home, "lower score", 42)

	assert not folder.exists()
	assert dest.exists()
	assert dest.parent == home / "_duplicates_review"
	assert (dest / "song.ini").exists()


def test_manifest_entry_includes_score(tmp_path):
	home = tmp_path / "library"
	home.mkdir()
	folder = _make_song_folder(home, "Weezer - My Name Is Jonas [dup2]")

	module.move_to_duplicates_review(folder, home, "lower score", 42)

	manifest_path = home / module.DUPLICATES_REVIEW_MANIFEST_FILENAME
	entries = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
	assert entries[0]["score"] == 42
	assert entries[0]["reason"] == "lower score"
	assert entries[0]["cross_volume"] is False
	assert entries[0]["verification"] == "not_applicable"


def test_move_handles_destination_name_collision(tmp_path):
	home = tmp_path / "library"
	home.mkdir()
	(home / "_duplicates_review").mkdir()
	_touch(home / "_duplicates_review" / "Weezer - My Name Is Jonas [dup2]" / "placeholder.txt")
	folder = _make_song_folder(home, "Weezer - My Name Is Jonas [dup2]")

	dest = module.move_to_duplicates_review(folder, home, "lower score", 42)

	assert dest.name == "Weezer - My Name Is Jonas [dup2] [dup1]"


def test_cross_volume_move_verifies_before_removing_source(tmp_path):
	home = tmp_path / "library"
	home.mkdir()
	folder = _make_song_folder(home, "Weezer - My Name Is Jonas [dup2]")

	with patch.object(module, "_dest_is_same_volume", return_value=False):
		dest = module.move_to_duplicates_review(folder, home, "lower score", 42)

	assert not folder.exists()
	assert (dest / "song.ini").exists()
	manifest_path = home / module.DUPLICATES_REVIEW_MANIFEST_FILENAME
	entries = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
	assert entries[0]["cross_volume"] is True
	assert entries[0]["verification"] == "ok"


def test_cross_volume_move_leaves_source_untouched_when_verification_fails(tmp_path):
	home = tmp_path / "library"
	home.mkdir()
	folder = _make_song_folder(home, "Weezer - My Name Is Jonas [dup2]")

	with patch.object(module, "_dest_is_same_volume", return_value=False), \
	     patch.object(module, "_folder_size_and_count", side_effect=[(999, 999), (0, 0)]):
		try:
			module.move_to_duplicates_review(folder, home, "lower score", 42)
			assert False, "expected a RuntimeError on verification failure"
		except RuntimeError:
			pass

	assert folder.exists()
	assert (folder / "song.ini").exists()


def test_dry_run_touches_nothing(tmp_path):
	home = tmp_path / "library"
	home.mkdir()
	folder = _make_song_folder(home, "Weezer - My Name Is Jonas [dup2]")

	dest = module.move_to_duplicates_review(folder, home, "lower score", 42, dry_run=True)

	assert folder.exists()
	assert dest is None
	assert not (home / "_duplicates_review").exists()
	assert not (home / module.DUPLICATES_REVIEW_MANIFEST_FILENAME).exists()
