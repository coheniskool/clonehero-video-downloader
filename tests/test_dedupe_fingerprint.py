"""confirm_group(): narrow a fuzzy-matched candidate group via audio fingerprinting.

Uses pyacoustid (wraps fpcalc) rather than hand-rolling Chromaprint
comparison -- compare_fingerprints() does proper decode + Hamming-distance
bit-pattern matching, not something worth reimplementing. Mocked here since
neither pyacoustid nor the fpcalc binary are installed in this environment
(matches the project's stated testing philosophy: real fpcalc invocation
against real audio isn't unit tested, only validated via --dry-run).
"""

from unittest.mock import MagicMock, patch

import dedupe_report as module


def _touch(path):
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_bytes(b"")


def test_confirms_two_folders_with_matching_fingerprints(tmp_path):
	folder_a = tmp_path / "Weezer - My Name Is Jonas"
	folder_b = tmp_path / "Weezer - My Name Is Jonas [dup2]"
	_touch(folder_a / "song.ogg")
	_touch(folder_b / "song.ogg")

	with patch.object(module, "acoustid", MagicMock()) as mock_acoustid:
		mock_acoustid.fingerprint_file.side_effect = [(180.0, "fp_a"), (180.0, "fp_a_close")]
		mock_acoustid.compare_fingerprints.return_value = 0.98

		confirmed = module.confirm_group([folder_a, folder_b])

	assert set(confirmed) == {folder_a, folder_b}


def test_rejects_a_folder_whose_fingerprint_does_not_match(tmp_path):
	# fuzzy title match slipped through, but the audio content is different --
	# this is what separates "Song X" from a same-named cover/different track
	folder_a = tmp_path / "Some Artist - Some Song"
	folder_b = tmp_path / "Some Artist - Some Song [dup2]"
	_touch(folder_a / "song.ogg")
	_touch(folder_b / "song.ogg")

	with patch.object(module, "acoustid", MagicMock()) as mock_acoustid:
		mock_acoustid.fingerprint_file.side_effect = [(180.0, "fp_a"), (200.0, "totally_different_fp")]
		mock_acoustid.compare_fingerprints.return_value = 0.10

		confirmed = module.confirm_group([folder_a, folder_b])

	assert confirmed == []


def test_returns_empty_when_fewer_than_two_folders_have_audio(tmp_path):
	folder_a = tmp_path / "Some Artist - Some Song"
	folder_b = tmp_path / "Some Artist - Some Song [dup2]"
	_touch(folder_a / "song.ogg")
	# folder_b has no audio file at all

	with patch.object(module, "acoustid", MagicMock()) as mock_acoustid:
		mock_acoustid.fingerprint_file.return_value = (180.0, "fp_a")

		confirmed = module.confirm_group([folder_a, folder_b])

	assert confirmed == []


def test_returns_empty_when_a_fingerprint_call_fails_never_raises(tmp_path):
	folder_a = tmp_path / "Some Artist - Some Song"
	folder_b = tmp_path / "Some Artist - Some Song [dup2]"
	_touch(folder_a / "song.ogg")
	_touch(folder_b / "song.ogg")

	with patch.object(module, "acoustid", MagicMock()) as mock_acoustid:
		mock_acoustid.fingerprint_file.side_effect = Exception("fpcalc not found")

		confirmed = module.confirm_group([folder_a, folder_b])

	assert confirmed == []


def test_returns_empty_when_fingerprint_support_unavailable(tmp_path):
	folder_a = tmp_path / "Some Artist - Some Song"
	folder_b = tmp_path / "Some Artist - Some Song [dup2]"
	_touch(folder_a / "song.ogg")
	_touch(folder_b / "song.ogg")

	with patch.object(module, "acoustid", None):
		confirmed = module.confirm_group([folder_a, folder_b])

	assert confirmed == []


def test_confirms_only_the_matching_subset_of_a_larger_group(tmp_path):
	# three fuzzy-matched candidates; only two are actually the same recording
	folder_a = tmp_path / "Artist - Song"
	folder_b = tmp_path / "Artist - Song [dup2]"
	folder_c = tmp_path / "Artist - Song [dup3]"
	for f in (folder_a, folder_b, folder_c):
		_touch(f / "song.ogg")

	with patch.object(module, "acoustid", MagicMock()) as mock_acoustid:
		mock_acoustid.fingerprint_file.side_effect = [(180.0, "fp_a"), (180.0, "fp_a_close"), (200.0, "fp_different")]
		mock_acoustid.compare_fingerprints.side_effect = [0.98, 0.05]  # b matches a, c does not

		confirmed = module.confirm_group([folder_a, folder_b, folder_c])

	assert set(confirmed) == {folder_a, folder_b}
