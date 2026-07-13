"""score_folder()/is_keeper_eligible()/select_keeper(): scoring + the hard
needs_review/unscanned keeper-exclusion gate.

The exclusion is enforced as a hard precondition (an assertion in
select_keeper()), not just documented intent -- picking a needs_review or
unscanned folder as a keeper would permanently promote a potentially wrong
chart under the right folder name, reopening the exact failure mode
SPEC-chart-rename.md exists to prevent.
"""

import dedupe_report as module


def test_score_folder_weights_instrument_completeness_most_heavily():
	video_meta = {"video_status": "present", "offset_confidence": 10}
	rich_ini = {f"diff_{i}": 3 for i in range(13)}
	sparse_ini = {}

	rich_score, rich_breakdown = module.score_folder("dir", video_meta, {
		"diff_band": 2, "diff_guitar": 3, "diff_guitar_coop": -1, "diff_rhythm": -1,
		"diff_bass": 1, "diff_drums": 5, "diff_drums_real": -1, "diff_keys": -1,
		"diff_guitarghl": -1, "diff_guitar_coop_ghl": -1, "diff_rhythm_ghl": -1,
		"diff_bassghl": -1, "diff_vocals": -1,
	}, None)
	sparse_score, sparse_breakdown = module.score_folder("dir", video_meta, {
		key: -1 for key in module.DIFF_KEYS
	}, None)

	assert rich_score > sparse_score
	assert rich_breakdown["instrument_count"] > sparse_breakdown["instrument_count"]


def test_score_folder_gives_no_video_points_when_absent():
	score, breakdown = module.score_folder("dir", {"video_status": "no_video"}, {key: -1 for key in module.DIFF_KEYS}, None)

	assert breakdown["has_video"] == 0


def test_score_folder_caps_offset_confidence_at_ten():
	score, breakdown = module.score_folder(
		"dir", {"video_status": "present", "offset_confidence": 99}, {key: -1 for key in module.DIFF_KEYS}, None
	)

	assert breakdown["offset_confidence"] == 10


def test_score_folder_metadata_completeness_counts_filled_keys():
	ini_fields = dict({key: -1 for key in module.DIFF_KEYS}, year="1999", genre="Rock", charter="", album="")

	score, breakdown = module.score_folder("dir", {}, ini_fields, None)

	assert breakdown["metadata_completeness"] == 4  # 2 filled keys * 2 points


def test_score_folder_chorus_signal_awarded_when_no_issues():
	ini_fields = {key: -1 for key in module.DIFF_KEYS}
	chorus_data = {"folderIssues": [], "metadataIssues": []}

	score, breakdown = module.score_folder("dir", {}, ini_fields, chorus_data)

	assert breakdown["chorus_signal"] == 5


def test_score_folder_chorus_signal_zero_when_issues_present():
	ini_fields = {key: -1 for key in module.DIFF_KEYS}
	chorus_data = {"folderIssues": ["missing_lyrics"], "metadataIssues": []}

	score, breakdown = module.score_folder("dir", {}, ini_fields, chorus_data)

	assert breakdown["chorus_signal"] == 0


def test_score_folder_chorus_signal_zero_when_no_chorus_data():
	ini_fields = {key: -1 for key in module.DIFF_KEYS}

	score, breakdown = module.score_folder("dir", {}, ini_fields, None)

	assert breakdown["chorus_signal"] == 0


def test_is_keeper_eligible_true_for_confirmed_ok():
	assert module.is_keeper_eligible({"chart_rename_status": "confirmed_ok"}) is True


def test_is_keeper_eligible_false_for_needs_review():
	assert module.is_keeper_eligible({"chart_rename_status": "needs_review"}) is False


def test_is_keeper_eligible_false_when_absent_unscanned():
	# absence must be treated identically to needs_review -- never "assumed clean"
	assert module.is_keeper_eligible({}) is False
	assert module.is_keeper_eligible({"chart_rename_status": None}) is False


def test_select_keeper_picks_the_highest_scoring_eligible_folder():
	scores = {"folder_a": 50, "folder_b": 80, "folder_c": 30}
	eligibility = {"folder_a": True, "folder_b": True, "folder_c": True}

	keeper = module.select_keeper(["folder_a", "folder_b", "folder_c"], scores, eligibility)

	assert keeper == "folder_b"


def test_select_keeper_never_picks_an_ineligible_folder_even_if_highest_scored():
	scores = {"folder_a": 50, "folder_b": 999, "folder_c": 30}
	eligibility = {"folder_a": True, "folder_b": False, "folder_c": True}  # b is needs_review/unscanned

	keeper = module.select_keeper(["folder_a", "folder_b", "folder_c"], scores, eligibility)

	assert keeper == "folder_a"


def test_select_keeper_returns_none_when_entire_group_is_ineligible():
	# real hard-gate case: every folder in the group is needs_review/unscanned --
	# skip the whole group and flag for manual attention, never auto-resolve
	scores = {"folder_a": 50, "folder_b": 80}
	eligibility = {"folder_a": False, "folder_b": False}

	keeper = module.select_keeper(["folder_a", "folder_b"], scores, eligibility)

	assert keeper is None
