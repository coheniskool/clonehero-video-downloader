# Spec: Duplicate Song Detection & Review for clonehero-video-downloader

## Objective

The user's ~5,131-song Clone Hero library has accumulated duplicate charts of the same song from different sources/charters over time. There's currently no tooling to find these or decide which copy to keep — that's done by hand, by ear, folder by folder.

This feature adds a new standalone pass, `dedupe_report.py`, that scans the library, groups song folders that are the same underlying song, scores each candidate in a group on quality/completeness signals, and moves everything except the highest-scoring folder ("the keeper") into a `_duplicates_review` folder for the user to manually confirm and eventually delete. It also flags cases where a lower-scored duplicate ("a loser") has something the keeper lacks — e.g. a Pro Drums track, a set difficulty rating, a background video — so the user knows a manual merge might be worth doing before discarding that folder.

**Real examples confirmed in the live library (2026-07-13)**: `Panic! At The Disco - I Write Sins Not Tragedies [dup2]`, `Red Hot Chili Peppers - Snow (Hey Oh) [dup253]`, and `Weezer - My Name Is Jonas [dup2]`/`[dup3]`/`[dup4]` all coexist alongside their plain-named counterparts in `M:\_Organized\Songs`. This isn't a hypothetical problem — it directly blocked an attempt to playtest the offset feature's pending `tasks/todo.md` Task 12, since it's unclear which copy Clone Hero loads or whether any copy has a settled offset. See `tasks/plan-next-features.md`'s Phase 5 for the follow-up task that re-attempts that playtest once this feature resolves these groups.

**User**: same solo hobbyist, same local/interactive/no-auth trust model as the rest of this project.

**Success looks like**: run `python dedupe_report.py`, and by the time it finishes, every confirmed duplicate group has exactly one folder left in place (the keeper) and the rest sitting untouched-but-relocated in `_duplicates_review`, plus a report showing why each keeper won and what — if anything — is worth hand-merging from a loser before it's deleted. Nothing is ever deleted by the script itself.

## Decisions Made During the 2026-07-13 Bridge Briefing

- **Keeper-selection must exclude `needs_review` AND unscanned folders — a tri-state, not a binary check.** `SPEC-chart-rename.md` persists `chart_rename_status` in `video_meta.json` as `confirmed_ok` or `needs_review`; its **absence** means "chart-rename hasn't reached this folder yet." Scoring/keeper-selection here must treat absence identically to `needs_review` — never as "assumed clean." Treating an unscanned folder as clean would reopen the exact failure mode chart-rename exists to prevent (a wrong chart under the right folder name), just through a different door. **If every folder in a candidate group is `needs_review` or unscanned, skip the whole group and flag it for manual attention instead of auto-selecting a keeper.**
- **RESOLVED (2026-07-14, Task 0): the real Chorus API schema is now confirmed**, sourced directly from reading [Bridge](https://github.com/Geomitron/Bridge)'s actual source (`search.service.ts`/`search.interface.ts`), not guessed or browser-reverse-engineered. Real base URL: `https://api.enchor.us` (confirmed live in Bridge's own `environment.prod.ts`); the previously-documented `chorus.fightthe.pw` is dead. Real endpoint for artist/title lookups: `POST /search/advanced` with a structured `{name: {value, exact, exclude}, artist: {...}, ...}` body — see Tech Stack below for the full shape.
- **CORRECTION: there is no "upvotes" or rating/popularity field anywhere in the real Chorus response.** This spec's original Code Style snippet (`score_folder()`) assumed `chorus_data.get("upvotes", 0)` as a "Chorus rating" scoring signal — that field does not exist in the real schema (confirmed by reading the actual `ChartData` type: `name`, `artist`, `album`, `genre`, `year`, `charter`, `chartId`, `songId`, `md5`, `chartHash`, `song_length`, many `diff_*` fields, `folderIssues`/`metadataIssues`, `modifiedTime`, `hasVideoBackground`, and Drive/pack metadata — no rating of any kind). The "Chorus rating signal" scoring category needs re-scoping at Task 12 — candidates: fewer `folderIssues`/`metadataIssues` (chart quality), more complete `diff_*` coverage (instrument completeness, may overlap with the existing local instrument-count signal), or dropping this category from Chorus entirely and relying only on local signals. Not decided here — flagged for Task 12's "resolve first" gate.
- **Folder moves need explicit same-volume vs. cross-volume handling, with a manifest.** A same-volume `Path.rename()`/`os.replace()` is atomic; a cross-volume move typically falls back to copy-then-delete, and an interruption mid-copy (crash, power loss, AV lock) mid-operation risks real, permanent data loss on an explicitly irreplaceable library. Every move must verify destination completeness (size/count, or a checksum for the cross-volume case) **before** removing anything from the source, and must be logged to a manifest (source path, destination path, score, reason) so the user can review or reconstruct what happened. This is the single highest-consequence finding from the review — it gates Task 13 before any real-library move runs.
- **`fpcalc` (Chromaprint) must come from the official AcoustID/Chromaprint release**, not an arbitrary download — same trust bar as the existing `ffmpeg` dependency, stated explicitly rather than assumed.
- **A duplicate-count estimate should be gathered before committing to the full fingerprinting pipeline's scope.** Unlike chart-rename (empirically grounded in a 3-of-7 hand audit), this spec's scope isn't yet grounded in a measured baseline for this library. A cheap fuzzy-match-only pass (no fingerprinting) run early in `/plan` should establish roughly how many candidate groups actually exist, so the scoring/borrow-candidate machinery is sized to the real problem.
- **Chorus's own Hash/Track-Hash lookup fields (visible in `enchor.us`'s live Advanced Search UI) are worth evaluating as a supplement or alternative to local Chromaprint fingerprinting** before locking in `fpcalc` as a hard dependency — if Chorus tracks a chart/audio hash server-side that this library's charts already carry, it could reduce or eliminate the need for local fingerprinting for at least the subset of songs sourced from Chorus.

## Tech Stack

- Python 3.x, same interpreter/version posture as the rest of the project.
- **Candidate grouping**: fuzzy artist/title match, reusing the existing `SequenceMatcher`-based normalization/scoring pattern already in `CH-VideoScript.py`'s spreadsheet matcher (`find_sheet_match`) rather than a new algorithm.
- **Duplicate confirmation**: audio fingerprinting via [Chromaprint](https://acoustid.org/chromaprint) (`pyacoustid` pip package, wraps the `fpcalc` CLI binary), obtained from the official AcoustID/Chromaprint release (see Decisions above). Only run within a fuzzy-matched candidate group, not library-wide (fingerprinting all 5,131 songs pairwise is unnecessary and slow) — this is what prevents a live/acoustic/remix version from being wrongly grouped with the studio original. Whether Chorus's own hash fields can substitute for some of this is an open evaluation (see Decisions above), not yet decided either way.
- **External binary**: `fpcalc` (Chromaprint) must be on PATH — new requirement, same category as the existing `ffmpeg`/`ffprobe` dependency (not pip-installable alone; document install steps and the official-release trust requirement in README).
- **Chorus signal**: `api.enchor.us` lookups via the shared `chorus_client.py`, best-effort — real request is `POST /search/advanced` with a structured `{name: {value, exact, exclude}, artist: {...}, ...}` body (all `AdvancedSearchSchema` fields must be present, nullable defaults for anything unused — see `SPEC-chorus-metadata.md`'s Tech Stack for the full real request/response shape, confirmed from Bridge's actual source). No rating/upvote field exists in the response (see Decisions above) — the exact signal this contributes to scoring is now an open question for Task 12, not "upvotes" as originally assumed.
- Reuses `find_song_ini()`, `find_song_audio()`, `find_video_file()` from `clonehero_video_offset.py` — no reimplementation.
- **Cross-spec dependency**: reads `chart_rename_status` from `video_meta.json` (written by `SPEC-chart-rename.md`) as a tri-state input to scoring (`confirmed_ok` / `needs_review` / absent — see Decisions above).
- No new framework, no database — persistence is a new per-group or per-library `dedupe_meta.json`/`dedupe_state.json` (exact shape TBD at `/plan`), mirroring the existing `video_meta.json` pattern, plus a move manifest (append-only log of every relocation: source, destination, score, reason, same-volume/cross-volume, verification result).

## Commands

```
Setup:  pip install -r pip-install.txt        (adds pyacoustid + whatever Chorus API client needs)
        fpcalc must be installed and on PATH   (official AcoustID/Chromaprint release — not pip-installable — verify with `fpcalc -version`)
Run:    python dedupe_report.py --library-path <path>
Dry run: python dedupe_report.py --dry-run     (computes groups/scores/report, moves nothing)
Test:   pytest tests/ -v
```

## Project Structure

```
dedupe_report.py           -> New standalone entry point: scans library, groups candidates
                               (fuzzy match), confirms groups (fingerprint), scores each
                               folder -- excluding needs_review/unscanned folders from
                               keeper eligibility (see Decisions above) -- picks a keeper,
                               moves losers to _duplicates_review/ via the same-volume/
                               cross-volume-aware move function, flags borrow-candidates,
                               writes the report and the move manifest. Imports
                               find_song_ini/find_song_audio/find_video_file from
                               clonehero_video_offset.py, and move_to_needs_review()-style
                               relocation mechanics shared with SPEC-chart-rename.md.
dedupe_scoring.py           -> Scoring logic: reads video_meta.json (including
                               chart_rename_status) + song.ini + file presence/quality
                               signals per folder, returns a numeric score + breakdown
                               (so the report can show *why* a folder won), and enforces
                               the needs_review/unscanned keeper exclusion as a hard
                               precondition (an assertion, not just documented intent).
                               Kept separate from dedupe_report.py's orchestration so
                               scoring weights can be tuned/tested in isolation.
chorus_client.py            -> Chorus (api.enchor.us) API lookup: best-effort, catches and
                               logs network/lookup failures, never blocks scoring. Built
                               from Bridge's (Geomitron) client source, not a guessed
                               schema (see Decisions above). Separate module so it can be
                               mocked out entirely in tests. Shared with
                               SPEC-chorus-metadata.md -- no second HTTP client.
pip-install.txt             -> +pyacoustid, +Chorus API client deps (requests or similar)
tests/
  test_dedupe_grouping.py       -> Fuzzy-match candidate grouping against synthetic folder
                                    name/song.ini fixtures, including a same-title-different-
                                    version case that must NOT be grouped by fuzzy match alone
  test_dedupe_fingerprint.py    -> Fingerprint-confirmation logic against canned fpcalc output
                                    (mocked — no real audio decode in unit tests)
  test_dedupe_scoring.py        -> Scoring function against synthetic video_meta.json/song.ini
                                    fixtures covering the full signal set, INCLUDING a fixture
                                    where every folder in a group is needs_review/unscanned
                                    (must skip the group entirely, never pick a keeper)
  test_dedupe_move.py           -> Atomic move-to-_duplicates_review, same-volume vs.
                                    cross-volume handling, destination-verification-before-
                                    source-removal, manifest logging, resumability, dry-run
                                    touches-zero-files guarantee
  test_borrow_candidates.py     -> Borrow-candidate flagging (chart track / diff_* / stem
                                    presence diffing) — asserts report-only, no file writes
  test_chorus_client.py         -> Chorus lookup against mocked responses, including
                                    not-found and network-failure paths (must not raise)
README.md                   -> To be updated to document dedupe_report.py, its flags, and
                               the _duplicates_review workflow
```

## Code Style

Match the existing project exactly:

```python
def score_folder(song_dir, video_meta, song_ini_fields, chorus_data):
	#returns (score, breakdown) -- breakdown is a dict of {signal_name: points} so the
	#report can show why a folder won, not just the final number
	breakdown = {}
	breakdown["has_video"] = 10 if video_meta.get("video_status") == "present" else 0
	breakdown["offset_confidence"] = min(video_meta.get("offset_confidence", 0), 10)
	breakdown["instrument_count"] = sum(
		1 for key in DIFF_KEYS if song_ini_fields.get(key, -1) != -1
	) * 5
	#no rating/upvote field exists in the real Chorus response (confirmed by
	#reading Bridge's actual ChartData type) -- chorus_data's contribution here
	#is a placeholder pending Task 12's re-scoping (folderIssues/metadataIssues
	#count, or dropping this category entirely); NOT "upvotes", which doesn't exist
	breakdown["chorus_signal"] = 0
	return sum(breakdown.values()), breakdown


def is_keeper_eligible(video_meta):
	#chart_rename_status absent (not yet scanned) is treated identically to
	#"needs_review" -- an unscanned folder's actual chart/audio content is just as
	#unconfirmed as a flagged one, and picking either as a keeper would permanently
	#promote a potentially wrong chart under the right folder name
	return video_meta.get("chart_rename_status") == "confirmed_ok"


def group_candidates(song_folders):
	#fuzzy artist+title match only -- this produces CANDIDATE groups, not confirmed
	#duplicates. confirm_group() below narrows each candidate group with audio
	#fingerprinting before anything gets scored or moved.
	...


def confirm_group(candidate_group):
	#fingerprints each folder's reference audio (find_song_audio) via fpcalc and only
	#keeps folders whose fingerprint actually matches -- this is what separates "Song X"
	#from "Song X (Live)" even though fuzzy title matching can't tell them apart
	...


def select_keeper(confirmed_group, scores):
	#hard precondition, not just documented intent: never select a folder that isn't
	#keeper-eligible. if none qualify, the whole group is skipped and flagged --
	#auto-picking among unconfirmed folders is worse than doing nothing
	eligible = [f for f in confirmed_group if is_keeper_eligible(f.video_meta)]
	if not eligible:
		return None  # caller flags the whole group for manual attention
	return max(eligible, key=lambda f: scores[f])
```

- Tabs for indentation (matches existing files)
- One function per discrete step, no classes (matches existing procedural style)
- Reuse existing logging pattern from `clonehero_video_offset.py` (`RotatingFileHandler`-based `logging` calls) rather than introducing a third logging mechanism
- Atomic folder moves: same-volume uses `Path.rename()`/`os.replace()` directly; cross-volume must verify destination completeness (size/count or checksum) before removing the source, never assume `shutil.move` is atomic across volumes
- Every move (either case) appended to a manifest log — source, destination, score, reason, volume-crossing, verification result
- Comments explain *why*, not *what*

## Testing Strategy

Same philosophy as the offset feature: this script moves folders around a real library, which is real corruption/data-loss risk if the grouping, scoring, or move logic is wrong, so grouping/scoring/move-mechanics get real unit tests; fingerprinting and Chorus API calls are mocked in unit tests and validated manually against the real library via `--dry-run`.

- **Unit-tested**: fuzzy candidate grouping (`test_dedupe_grouping.py`) including the critical negative case — same title, different version tag ("Live"/"Acoustic"/"Remix") must NOT be treated as an automatic duplicate by fuzzy match alone. Fingerprint-confirmation logic against canned `fpcalc` output, not real audio (`test_dedupe_fingerprint.py`). Scoring function against synthetic fixtures covering the full signal set, including the all-`needs_review`/unscanned-group skip case (`test_dedupe_scoring.py`). Move-to-review-folder mechanics: atomicity, same-volume/cross-volume handling, destination verification before source removal, manifest logging, resumability, `--dry-run` zero-file-touched guarantee (`test_dedupe_move.py`). Borrow-candidate flagging produces correct flags and never writes to any chart/song.ini/audio file (`test_borrow_candidates.py`). Chorus client against mocked HTTP responses, including not-found and network-failure paths that must degrade gracefully, never raise (`test_chorus_client.py`).
- **Not unit-tested** (low value / requires real binaries): real `fpcalc` invocation against real audio, real Chorus API round-trips. Validated by `--dry-run` output inspection against a real library subset, plus manual review of a sample of moved groups before the first full-library run.
- No CI — local script, run on-demand, matches the rest of the project.

## Boundaries

- **Always**:
  - Confirm a candidate group with audio fingerprinting before treating it as a real duplicate — fuzzy title match alone is a grouping heuristic, never sufficient to move a folder
  - Exclude `needs_review` and unscanned (`chart_rename_status` absent) folders from keeper eligibility, enforced as a hard precondition in `select_keeper()`, not just documented intent — skip the whole group if none qualify
  - Move (never delete) losing duplicates, into `_duplicates_review` at the library root, folder contents fully intact
  - Detect same-volume vs. cross-volume moves; for cross-volume, verify destination completeness before removing the source
  - Log every move to a manifest (source, destination, score, reason, volume-crossing, verification result)
  - Log every keeper decision with its full score breakdown, so a wrong pick is auditable and correctable by hand
  - Log every borrow-candidate flag (chart-track / `song.ini` diff-field / stem-audio differences) to the report — never act on them automatically
  - Persist group/move state so reruns skip already-resolved groups (resumability, matching `video_meta.json`'s existing pattern)
  - Support `--dry-run` so grouping/scoring/flags can be reviewed before any folder is moved
  - Degrade gracefully on Chorus API failures/not-found — never block or fail a group's scoring because of a network issue

- **Ask first**:
  - Scoring weights/formula specifics (this spec establishes the signal categories; exact point values are a `/plan`-time decision to review before implementation, informed by the duplicate-count estimate — see Decisions above)
  - Adding `pyacoustid` or any Chorus-client HTTP dependency beyond what's minimally needed
  - The exact shape of `_duplicates_review`'s naming (flat vs. grouped-by-original-title subfolders) if a naming collision case comes up
  - Whether Chorus hash fields can/should reduce reliance on local fingerprinting (see Decisions above) — an evaluation, not a decided direction yet

- **Never**:
  - Never delete a song folder, chart, audio, or metadata file — moving to `_duplicates_review` is the only relocation action this script takes; deletion from that folder is entirely the user's manual step, forever out of scope
  - Never write to a keeper's `.chart`/`.mid` file, `song.ini`, or audio files to "borrow" content from a loser — v1 is flag/report-only for this; auto-merge is explicitly out of scope until re-scoped (see Open Questions)
  - Never treat a fuzzy-match candidate group as confirmed duplicates without fingerprint confirmation
  - Never select a `needs_review` or unscanned folder as a keeper, under any circumstance
  - Never remove a source folder in a cross-volume move before destination completeness is verified
  - Never let a Chorus API failure abort a run
  - Never obtain `fpcalc` from anywhere but the official AcoustID/Chromaprint release

## Success Criteria

- [ ] A duplicate-count estimate (fuzzy-match-only pass, no fingerprinting) is gathered before the full pipeline's scope is finalized
- [ ] `chorus_client.py`'s real request/response schema sourced from Bridge's client code before this spec's Chorus-rating-signal code is implemented
- [ ] Running `python dedupe_report.py --library-path <path>` against the real library produces confirmed duplicate groups (fingerprint-verified, not just fuzzy-matched) with zero known false positives on a manually spot-checked sample
- [ ] Each duplicate group has exactly one keeper left in its original location; all other group members are relocated intact to `_duplicates_review`, verified by folder diff (nothing lost, nothing modified)
- [ ] Zero `needs_review` or unscanned folders are ever selected as a keeper, including the all-such-group case (verified with a dedicated test fixture, not just code review)
- [ ] Every move is logged to a manifest; a cross-volume move's destination is verified complete before its source is removed (verified with a dedicated test that simulates an interrupted cross-volume move)
- [ ] The report shows, per group: which folder won, its full score breakdown, and any borrow-candidate flags for the losers (missing instrument parts / unset difficulties / missing stems that a loser has and the keeper doesn't)
- [ ] `test_dedupe_grouping.py`'s negative case (same title, different version) passes — fuzzy match alone never triggers a move
- [ ] `--dry-run` produces the full report with zero folders moved, verified via before/after folder-listing diff
- [ ] A second run against an already-processed library is a no-op except for genuinely new duplicate groups (resumability)
- [ ] Chorus API lookups degrade gracefully — a run with network disabled still completes and produces a report (with Chorus-sourced score components at 0/absent)
- [ ] **Deferred to the user**: manually review at least one full `_duplicates_review` batch and confirm the keeper picks look right before deleting anything

## Open Questions

- **Exact scoring weights** — this spec establishes categories (video presence/confidence, offset confidence, instrument/difficulty completeness, package completeness, a Chorus-derived signal, fingerprint-confirmed-duplicate as the gate) but not point values. Needs a concrete proposal reviewed at `/plan` time, informed by the duplicate-count estimate and what real duplicate groups in the library actually look like. **Now also needs the Chorus signal itself re-scoped** — the real API has no rating/upvote field (see Decisions above), so this category is `folderIssues`/`metadataIssues`-based chart-quality, `diff_*` completeness, or dropped entirely, not "Chorus rating" as originally conceived.
- **`_duplicates_review` folder-naming/collision strategy** — deferred, see Boundaries.
- **Chart-merge automation beyond flag-only** — explicitly out of scope for this spec per the user's decision (tempo/sync-map incompatibility between independently-charted duplicates makes blind note-copying corruption-risk). If ever revisited, it needs its own spec and its own sign-convention-style verification gate, same pattern as the offset feature's Task 6.
- **Fingerprinting performance at library scale, and whether Chorus hash fields reduce the need for it** — fpcalc runs only within already-fuzzy-matched candidate groups (not all 5,131 songs pairwise), but actual wall-clock cost against the real library is unmeasured until `/plan`/early implementation, and whether Chorus's own hash data can substitute for some of this is a fresh evaluation from the 2026-07-13 review, not yet decided.
- **`.sng`-packaged folders** (found during `SPEC-chart-rename.md`'s 2026-07-14 documentation review — not observed in this library, but real and documented): `find_song_audio()`/`fpcalc` can't fingerprint a folder whose audio lives inside a single-file `.sng` container without first extracting it, which this spec doesn't currently plan for. Low priority since none exist in this library today, but worth the same defensive skip-or-flag treatment chart-rename adopted if one is ever encountered, rather than an unhandled crash.
