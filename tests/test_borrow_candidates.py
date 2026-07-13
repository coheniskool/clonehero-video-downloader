"""flag_borrow_candidates(): report-only flags for what a loser has that the
keeper lacks (e.g. a Pro Drums track, a set difficulty, a background video).

Never acts on these -- purely informational so the user can decide whether
a manual merge is worth doing before deleting a loser.
"""

import dedupe_report as module


def _all_diff_keys(**overrides):
	fields = {key: -1 for key in module.DIFF_KEYS}
	fields.update(overrides)
	return fields


def test_flags_a_difficulty_the_loser_has_and_keeper_lacks():
	keeper = _all_diff_keys()
	loser = _all_diff_keys(diff_drums_real=4)

	flags = module.flag_borrow_candidates(keeper, {}, loser, {})

	assert any("diff_drums_real" in f for f in flags)


def test_does_not_flag_when_keeper_already_has_the_difficulty():
	keeper = _all_diff_keys(diff_drums_real=3)
	loser = _all_diff_keys(diff_drums_real=4)

	flags = module.flag_borrow_candidates(keeper, {}, loser, {})

	assert not any("diff_drums_real" in f for f in flags)


def test_does_not_flag_when_neither_has_the_difficulty():
	keeper = _all_diff_keys()
	loser = _all_diff_keys()

	flags = module.flag_borrow_candidates(keeper, {}, loser, {})

	assert flags == []


def test_flags_a_background_video_the_loser_has_and_keeper_lacks():
	keeper_video = {"video_status": "no_video"}
	loser_video = {"video_status": "present"}

	flags = module.flag_borrow_candidates(_all_diff_keys(), keeper_video, _all_diff_keys(), loser_video)

	assert any("video" in f.lower() for f in flags)


def test_does_not_flag_video_when_keeper_already_has_one():
	keeper_video = {"video_status": "present"}
	loser_video = {"video_status": "present"}

	flags = module.flag_borrow_candidates(_all_diff_keys(), keeper_video, _all_diff_keys(), loser_video)

	assert not any("video" in f.lower() for f in flags)


def test_flags_multiple_differences_at_once():
	keeper = _all_diff_keys()
	loser = _all_diff_keys(diff_drums_real=4, diff_vocals=2)

	flags = module.flag_borrow_candidates(keeper, {}, loser, {})

	assert len(flags) == 2
