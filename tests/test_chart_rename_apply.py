"""process_chart_folder_names(): verify-then-rename with a collision guard.

Ties together scan_song_folder_chart_names() (detection) and
verify_chart_content_match() (content verification) into the actual rename
decision -- confirmed_ok (already correct, or safely renamed), needs_review
(content unconfirmed, collision, or nothing to verify against), or
skipped_sng (Clone Hero's newer single-file container, untouched).

Does not yet cover audio-stems/album-art combination, folder relocation, or
persistence -- those are separate, later increments layered on top.
"""

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
