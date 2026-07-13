"""process_chart_folder_names(): verify-then-rename with a collision guard.

Ties together scan_song_folder_chart_names() (detection) and
verify_chart_content_match() (content verification) into the actual rename
decision -- confirmed_ok (already correct, or safely renamed), needs_review
(content unconfirmed, collision, or nothing to verify against), or
skipped_sng (Clone Hero's newer single-file container, untouched).

move_to_needs_review() relocates a folder to _needs_review/ at the library
root, same-volume vs. cross-volume aware, with a JSONL manifest -- a cross-
volume move must verify the destination is complete before removing the
source, since an interrupted copy-then-delete is real, permanent data loss
on an irreplaceable library.

Does not yet cover audio-stems/album-art combination or status persistence
-- those are separate, later increments layered on top.
"""

import json
from unittest.mock import patch

import clonehero_video_offset as module


def _touch(path, content=None):
	path.parent.mkdir(parents=True, exist_ok=True)
	if content is None:
		path.write_bytes(b"")
	else:
		path.write_text(content, encoding="utf-8")


def _chart_text(name, artist):
	return '﻿[Song]\n{\n  Name = "%s"\n  Artist = "%s"\n  Offset = 0\n}\n' % (name, artist)


def _ini_text(name, artist, song_length=None):
	lines = ["[Song]", f"name = {name}", f"artist = {artist}"]
	if song_length is not None:
		lines.append(f"song_length = {song_length}")
	return "\n".join(lines) + "\n"


def test_confirmed_ok_when_already_literal(tmp_path):
	_touch(tmp_path / "song.ini", _ini_text("Kryptonite", "3 Doors Down"))
	_touch(tmp_path / "notes.chart", _chart_text("Kryptonite", "3 Doors Down"))

	result = module.process_chart_folder_names(tmp_path)

	assert result["status"] == "confirmed_ok"
	assert (tmp_path / "song.ini").exists()


def test_renames_id_suffixed_ini_and_chart_when_content_verified(tmp_path):
	_touch(tmp_path / "song_2400.ini", _ini_text("Kryptonite", "3 Doors Down"))
	_touch(tmp_path / "notes_454.chart", _chart_text("Kryptonite", "3 Doors Down"))

	result = module.process_chart_folder_names(tmp_path)

	assert result["status"] == "confirmed_ok"
	assert (tmp_path / "song.ini").exists()
	assert (tmp_path / "notes.chart").exists()
	assert not (tmp_path / "song_2400.ini").exists()
	assert not (tmp_path / "notes_454.chart").exists()


def test_needs_review_for_real_mr_roboto_content_mismatch(tmp_path):
	# real shape: song.ini says "Mr. Roboto", chart embeds "Rock & Roll Feeling"
	_touch(tmp_path / "song_819.ini", _ini_text("Mr. Roboto", "Styx"))
	_touch(tmp_path / "notes_454.chart", _chart_text("Rock & Roll Feeling", "Styx"))

	result = module.process_chart_folder_names(tmp_path)

	assert result["status"] == "needs_review"
	# nothing renamed -- files left exactly as found
	assert (tmp_path / "song_819.ini").exists()
	assert (tmp_path / "notes_454.chart").exists()
	assert not (tmp_path / "song.ini").exists()


def test_needs_review_when_ini_collides_with_existing_canonical_file(tmp_path):
	_touch(tmp_path / "song.ini", _ini_text("Kryptonite", "3 Doors Down"))
	_touch(tmp_path / "song_2400.ini", _ini_text("Kryptonite", "3 Doors Down"))
	_touch(tmp_path / "notes.chart", _chart_text("Kryptonite", "3 Doors Down"))

	result = module.process_chart_folder_names(tmp_path)

	assert result["status"] == "needs_review"
	# neither file touched -- never overwrite an existing canonical file
	assert (tmp_path / "song_2400.ini").exists()


def test_needs_review_when_chart_collides_with_existing_canonical_file(tmp_path):
	_touch(tmp_path / "song_2400.ini", _ini_text("Kryptonite", "3 Doors Down"))
	_touch(tmp_path / "notes.chart", _chart_text("Kryptonite", "3 Doors Down"))
	_touch(tmp_path / "notes_454.chart", _chart_text("Kryptonite", "3 Doors Down"))

	result = module.process_chart_folder_names(tmp_path)

	assert result["status"] == "needs_review"
	assert (tmp_path / "song_2400.ini").exists()


def test_needs_review_when_no_ini_present(tmp_path):
	_touch(tmp_path / "notes.chart", _chart_text("Kryptonite", "3 Doors Down"))

	result = module.process_chart_folder_names(tmp_path)

	assert result["status"] == "needs_review"


def test_needs_review_when_no_chart_or_mid_present(tmp_path):
	_touch(tmp_path / "song_2400.ini", _ini_text("Kryptonite", "3 Doors Down"))

	result = module.process_chart_folder_names(tmp_path)

	assert result["status"] == "needs_review"


def test_skipped_sng_when_sng_packaged_never_touches_anything(tmp_path):
	_touch(tmp_path / "song.sng")
	_touch(tmp_path / "leftover_819.ini")

	result = module.process_chart_folder_names(tmp_path)

	assert result["status"] == "skipped_sng"
	assert (tmp_path / "leftover_819.ini").exists()


# --- move_to_needs_review ----------------------------------------------------

def _make_song_folder(home_folder, name="Styx - Mr. Roboto"):
	folder = home_folder / name
	_touch(folder / "song_819.ini", "[Song]\nname = Mr. Roboto\n")
	_touch(folder / "notes_454.chart", _chart_text("Rock & Roll Feeling", "Styx"))
	return folder


def test_same_volume_move_relocates_folder_intact(tmp_path):
	home = tmp_path / "library"
	home.mkdir()
	song_dir = _make_song_folder(home)

	dest = module.move_to_needs_review(song_dir, home, "content mismatch")

	assert not song_dir.exists()
	assert dest.exists()
	assert dest.parent == home / "_needs_review"
	assert (dest / "song_819.ini").exists()
	assert (dest / "notes_454.chart").exists()


def test_same_volume_move_appends_manifest_entry(tmp_path):
	home = tmp_path / "library"
	home.mkdir()
	song_dir = _make_song_folder(home)

	module.move_to_needs_review(song_dir, home, "content mismatch")

	manifest_path = home / module.NEEDS_REVIEW_MANIFEST_FILENAME
	entries = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
	assert len(entries) == 1
	assert entries[0]["reason"] == "content mismatch"
	assert entries[0]["cross_volume"] is False
	assert entries[0]["verification"] == "not_applicable"


def test_move_handles_destination_name_collision(tmp_path):
	home = tmp_path / "library"
	home.mkdir()
	(home / "_needs_review").mkdir()
	_touch(home / "_needs_review" / "Styx - Mr. Roboto" / "placeholder.txt")
	song_dir = _make_song_folder(home)

	dest = module.move_to_needs_review(song_dir, home, "content mismatch")

	assert dest.name == "Styx - Mr. Roboto [dup1]"
	assert (home / "_needs_review" / "Styx - Mr. Roboto" / "placeholder.txt").exists()


def test_cross_volume_move_verifies_before_removing_source(tmp_path):
	home = tmp_path / "library"
	home.mkdir()
	song_dir = _make_song_folder(home)

	with patch.object(module, "_dest_is_same_volume", return_value=False):
		dest = module.move_to_needs_review(song_dir, home, "content mismatch")

	assert not song_dir.exists()
	assert (dest / "song_819.ini").exists()
	manifest_path = home / module.NEEDS_REVIEW_MANIFEST_FILENAME
	entries = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
	assert entries[0]["cross_volume"] is True
	assert entries[0]["verification"] == "ok"


def test_cross_volume_move_leaves_source_untouched_when_verification_fails(tmp_path):
	home = tmp_path / "library"
	home.mkdir()
	song_dir = _make_song_folder(home)

	with patch.object(module, "_dest_is_same_volume", return_value=False), \
	     patch.object(module, "_folder_size_and_count", side_effect=[(999, 999), (0, 0)]):
		try:
			module.move_to_needs_review(song_dir, home, "content mismatch")
			assert False, "expected a RuntimeError on verification failure"
		except RuntimeError:
			pass

	# source must still exist, completely untouched -- an interrupted/incomplete
	# cross-volume copy is not grounds to delete the only good copy
	assert song_dir.exists()
	assert (song_dir / "song_819.ini").exists()
