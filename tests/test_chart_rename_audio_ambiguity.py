"""Audio-stem role naming classification.

Clone Hero requires audio stems to be named literally per role (song.ogg,
guitar.ogg, drums_1.ogg, ...) -- confirmed against the official wiki and the
canonical chart-format stem reference, NOT prefix-matched as an earlier draft
of this spec wrongly assumed (see SPEC-chart-rename.md's "Never Touch Audio"
correction). A real census (2026-07-14) found 1,083 of 5,130 real library
folders (~21%) missing a literal song.* file, 250 of those with multiple
conflicting candidates -- this module's job is to classify each recognized
role as literal-match / single-candidate-rename / multiple-candidates-review,
never to guess among genuine candidates.
"""

import clonehero_video_offset as module


def _touch(path):
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_bytes(b"")


def test_ok_when_all_present_stems_are_literal(tmp_path):
	_touch(tmp_path / "song.ogg")
	_touch(tmp_path / "guitar.ogg")
	_touch(tmp_path / "drums_1.ogg")
	_touch(tmp_path / "drums_2.ogg")

	result = module.scan_song_folder_audio_stems(tmp_path)

	assert result["status"] == "ok"


def test_ok_when_folder_has_no_audio_at_all(tmp_path):
	# not this check's job to require audio exists -- that's find_song_audio's concern
	result = module.scan_song_folder_audio_stems(tmp_path)

	assert result["status"] == "ok"


def test_rename_candidate_when_exactly_one_id_suffixed_candidate(tmp_path):
	_touch(tmp_path / "song_1877.ogg")

	result = module.scan_song_folder_audio_stems(tmp_path)

	assert result["status"] == "rename_candidate"
	assert "song_1877.ogg" in result["detail"]


def test_needs_review_for_real_kryptonite_shaped_ambiguity(tmp_path):
	# real folder contents from M:\_organized\Test\3 Doors Down - Kryptonite:
	# four guitar candidates, two rhythm candidates, two conflicting drum-mixing
	# conventions (single-track drums_183.ogg AND split drums_1_512..drums_4_427.ogg)
	_touch(tmp_path / "song_1877.ogg")
	_touch(tmp_path / "guitar_1760.ogg")
	_touch(tmp_path / "guitar_1846.ogg")
	_touch(tmp_path / "guitar_2051.ogg")
	_touch(tmp_path / "guitar_925.ogg")
	_touch(tmp_path / "rhythm_1315.ogg")
	_touch(tmp_path / "rhythm_647.ogg")
	_touch(tmp_path / "drums_183.ogg")
	_touch(tmp_path / "drums_1_512.ogg")
	_touch(tmp_path / "drums_2_512.ogg")
	_touch(tmp_path / "drums_3_505.ogg")
	_touch(tmp_path / "drums_4_427.ogg")
	_touch(tmp_path / "vocals_1237.ogg")
	_touch(tmp_path / "crowd_360.ogg")

	result = module.scan_song_folder_audio_stems(tmp_path)

	assert result["status"] == "needs_review"
	assert "guitar" in result["detail"].lower()


def test_needs_review_when_literal_and_id_suffixed_both_exist_for_same_role(tmp_path):
	_touch(tmp_path / "guitar.ogg")
	_touch(tmp_path / "guitar_2051.ogg")

	result = module.scan_song_folder_audio_stems(tmp_path)

	assert result["status"] == "needs_review"


def test_recognizes_the_complete_reserved_stem_role_set(tmp_path):
	# preview and the vocals_* family were missing from an earlier draft of this
	# check -- confirmed against https://thenathannator.github.io/GuitarGame_
	# ChartFormats/Chart-File-Formats/Supported-Audio-Files/
	_touch(tmp_path / "preview_99.ogg")
	_touch(tmp_path / "vocals_explicit_12.ogg")

	result = module.scan_song_folder_audio_stems(tmp_path)

	assert result["status"] == "rename_candidate"
	assert "preview" in result["detail"].lower()
	assert "vocals_explicit" in result["detail"].lower()


def test_does_not_confuse_unrelated_files_for_stem_roles(tmp_path):
	_touch(tmp_path / "song.ogg")
	_touch(tmp_path / "notes.mid")
	_touch(tmp_path / "video.mp4")
	_touch(tmp_path / "video_meta.json")

	result = module.scan_song_folder_audio_stems(tmp_path)

	assert result["status"] == "ok"
