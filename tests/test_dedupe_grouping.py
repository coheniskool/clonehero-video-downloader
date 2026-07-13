"""Fuzzy candidate grouping against synthetic folder-name fixtures.

Produces CANDIDATE groups only -- confirm_group() (fingerprinting, Task 11b)
narrows each candidate group to fingerprint-confirmed duplicates before
anything gets scored or moved. The critical negative case: same title,
different version tag ("Live"/"Acoustic"/"Remix") must NOT be grouped by
fuzzy match alone -- a live recording and the studio original are
different underlying audio.

Reuses the real census (Task 10) finding: bracket-suffix noise like
"[dup253]" is a known real pattern in this library and must be stripped
before fuzzy-matching, not just typos/case differences.
"""

import dedupe_report as module


def _make_folders(tmp_path, names):
	folders = []
	for name in names:
		folder = tmp_path / name
		folder.mkdir()
		folders.append(folder)
	return folders


def test_groups_real_dup_suffixed_folders(tmp_path):
	folders = _make_folders(tmp_path, [
		"Weezer - My Name Is Jonas",
		"Weezer - My Name Is Jonas [dup2]",
		"Weezer - My Name Is Jonas [dup3]",
		"Weezer - My Name Is Jonas [dup4]",
	])

	groups = module.group_candidates(folders)

	assert len(groups) == 1
	assert len(groups[0]) == 4


def test_groups_the_real_snow_hey_oh_case(tmp_path):
	folders = _make_folders(tmp_path, [
		"Red Hot Chili Peppers - Snow (Hey Oh)",
		"Red Hot Chili Peppers - Snow (Hey Oh) [dup253]",
	])

	groups = module.group_candidates(folders)

	assert len(groups) == 1
	assert len(groups[0]) == 2


def test_does_not_group_live_version_with_studio_original(tmp_path):
	folders = _make_folders(tmp_path, [
		"Fall Out Boy - Centuries",
		"Fall Out Boy - Centuries (Live)",
	])

	groups = module.group_candidates(folders)

	assert groups == []


def test_does_not_group_acoustic_version_with_studio_original(tmp_path):
	folders = _make_folders(tmp_path, [
		"Some Artist - Some Song",
		"Some Artist - Some Song (Acoustic)",
	])

	groups = module.group_candidates(folders)

	assert groups == []


def test_does_not_group_remix_with_original(tmp_path):
	folders = _make_folders(tmp_path, [
		"Some Artist - Some Song",
		"Some Artist - Some Song (Remix)",
	])

	groups = module.group_candidates(folders)

	assert groups == []


def test_groups_two_live_versions_with_each_other(tmp_path):
	# same version tag on both sides -- these ARE duplicates of each other
	folders = _make_folders(tmp_path, [
		"Fall Out Boy - Centuries (Live)",
		"Fall Out Boy - Centuries (Live) [dup2]",
	])

	groups = module.group_candidates(folders)

	assert len(groups) == 1
	assert len(groups[0]) == 2


def test_does_not_group_different_songs_by_the_same_artist(tmp_path):
	folders = _make_folders(tmp_path, [
		"3 Doors Down - Kryptonite",
		"3 Doors Down - Here Without You",
	])

	groups = module.group_candidates(folders)

	assert groups == []


def test_does_not_group_same_song_by_different_artists(tmp_path):
	folders = _make_folders(tmp_path, [
		"Blink-182 - All the Small Things",
		"Someone Else - All the Small Things",
	])

	groups = module.group_candidates(folders)

	assert groups == []


def test_handles_a_singleton_library_with_no_duplicates(tmp_path):
	folders = _make_folders(tmp_path, [
		"My Chemical Romance - Helena",
		"Panic! at the Disco - I Write Sins Not Tragedies",
	])

	groups = module.group_candidates(folders)

	assert groups == []
