# Implementation Plan: Chart Rename, Chorus Metadata Enrichment, Duplicate Detection

## Context

Three specs are queued behind the completed offset feature (`tasks/plan.md`/`todo.md`, Task 12 still deferred to the user):

- `SPEC-chart-rename.md` — new
- `SPEC-chorus-metadata.md` — new
- `SPEC-duplicate-detection.md` — written previously, no plan yet

They're planned together because two of them share a real dependency (`chorus_client.py`) and a third has a genuine correctness interaction with the first that neither spec called out individually.

**2026-07-13 update — bridge briefing conducted, findings folded into all three specs and this plan.** A 5-officer review (`.bridge/briefings/2026-07-13-next-features-plan-review.md`) reached a unanimous ENGAGE WITH CAUTION verdict and, alongside it, live research resolved the Chorus API's real host (confirmed `https://api.enchor.us/search`; the previously-documented `chorus.fightthe.pw` is dead, HTTP 404) and confirmed album art is not tracked by the service at all (no field anywhere in the live Advanced Search UI). Six must-fix items came out of that review and are now built into the tasks below, not left as follow-ups:

1. **`chorus_client.py` must be built from [Bridge](https://github.com/Geomitron/Bridge)'s source**, not a guessed schema — browser-based interception of the real endpoint failed silently twice during the review.
2. **The `needs_review` exclusion is now a hard tri-state gate**, not a soft dependency: `SPEC-chart-rename.md` persists `chart_rename_status` (`confirmed_ok`/`needs_review`, absence = not yet scanned) in `video_meta.json`; `SPEC-duplicate-detection.md`'s keeper-selection must treat `needs_review` and absence identically, enforced as a hard precondition (an assertion), with an all-such-group skip path.
3. **Every Chorus-sourced `song.ini` field must pass a strict sanitizer** before it's regex-spliced into the file — control chars, embedded `[`/`]`/`;`/`#`, embedded newlines, and bad encoding are all rejected.
4. **Duplicate-detection's folder move needs same-volume/cross-volume handling and a manifest** — a cross-volume move risks real data loss on an interrupted copy; destination completeness must be verified before source removal, and every move is logged.
5. **`SPEC-chorus-metadata.md` now commits to the same per-item logging + aggregate summary contract its siblings have** — a failed/skipped lookup used to be silent.
6. **`SPEC-chart-rename.md`'s own previously-open questions are now resolved, not re-deferred**: `needs_review` folders are physically relocated to `_needs_review/` (mirroring `_duplicates_review`), the `.chart` fuzzy-match threshold is fixed at ≥85 (both Name and Artist), and the `.mid` duration tolerance is fixed at ±2000ms.

**2026-07-13 follow-up correction — verified against the official Clone Hero Wiki and the real library.** `SPEC-chart-rename.md`'s original claim that audio stems don't need touching ("Clone Hero prefix-matches them fine") is **not confirmed by documentation and appears to be wrong** — official guidance says audio must be named literally (`song.ogg`, `guitar.ogg`, `drums_1.ogg`-`drums_4.ogg`, etc.), with no documented tolerance for ID-suffixed names. Direct inspection of `M:\_organized\Test\3 Doors Down - Kryptonite` (this spec's own "safe, confirmed" example) found it has **no literal-named audio at all** — only ID-suffixed files, including four candidate guitar files and two conflicting drum-mixing conventions in one folder. **Confirmed by the user 2026-07-13: Kryptonite currently produces no audio in Clone Hero at all** — not a theoretical risk, an already-broken song. Chart-rename's scope now includes an audio-stem naming check (Task 3b below).

**2026-07-14 final-review follow-up — verified against the official Clone Hero Wiki once more before `/build`, found two more real gaps in `SPEC-chart-rename.md`'s scope.** Album art (`album.png`/`album.jpg`) is also a required-literal-filename item per official docs, and this spec's scope never covered it — direct inspection shows every ID-suffixed-chart folder found so far (Kryptonite, Mr. Roboto, You Only Live Once) *also* has ID-suffixed album art (`album_827.png`, `album_822.jpg`, `album_525.jpg`), the same generating bug hitting more file types than originally scoped. Added Task 3c below. Separately, the audio-stem role list was incomplete against the authoritative reference ([Supported Audio Files](https://thenathannator.github.io/GuitarGame_ChartFormats/Chart-File-Formats/Supported-Audio-Files/)) — missing `preview` and the `vocals_1`/`vocals_2`/`vocals_explicit(_1/_2)` variants, now corrected in Task 3b and the spec. Also added a cheap defensive guard: any folder containing a `.sng` file (Clone Hero's newer single-file container format, not observed in this library but real and documented) is skipped entirely by all of chart-rename's checks.

**2026-07-13 second follow-up — the offset feature's Task 12 playtest is blocked, and it's the same root problem.** The user tried to playtest one of the other 4 clean-looking Test-folder songs instead of Kryptonite and reported being unable to, because those songs are "stuck as duplicates." Direct inspection of the real library (`M:\_Organized\Songs`, not just the small `M:\_organized\Test` staging folder) confirms this concretely:

- `Panic! At The Disco - I Write Sins Not Tragedies [dup2]` exists alongside the plain-named folder
- `Red Hot Chili Peppers - Snow (Hey Oh) [dup253]` exists alongside the plain-named folder
- `Weezer - My Name Is Jonas [dup2]`, `[dup3]`, `[dup4]` all exist alongside the plain-named folder

It's unknown which copy Clone Hero actually loads, or whether any duplicate carries a computed `video_start_time` — so playtesting any of these songs today doesn't reliably test anything. This is a **real, live instance of exactly the problem `SPEC-duplicate-detection.md` exists to solve**, not a new independent bug. A new phase (Phase 5 below) is added specifically to close this loop once Track C can resolve it — inserted after Track C rather than at the very end, since it depends on Track C's output and unblocks a long-pending item on the *other* feature's todo list (`tasks/todo.md` Task 12), which is worth resolving before final integration/docs.

## Dependency Graph

```
Task 0: Read Bridge's (Geomitron) source for the real api.enchor.us
        request/response schema  [GATE — blocks Task 6]
        (host already confirmed live during the 2026-07-13 review;
        this task is schema-extraction, not host-discovery)
   |
   +--> Track A: Chart Rename (no dependency on Task 0 — starts immediately)
   |       Task 1: ID-suffix detection (song.ini/notes.chart/notes.mid)
   |          |
   |          +--> Task 2: .chart Name/Artist fuzzy verification (>=85 threshold)
   |          +--> Task 3: .mid duration-vs-song_length fallback (+/-2000ms)
   |          +--> [resolve open question] --> Task 3b: Audio-stem naming check
   |          |     per role (complete reserved set: preview/song/guitar/rhythm/bass/
   |          |     keys/drums(_1-4)/vocals(_1/_2/_explicit(_1/_2))/crowd)
   |          +--> Task 3c: Album-art naming check (album.png/.jpg/.jpeg) + .sng guard
   |                (skip folders containing a .sng file entirely)
   |                 |
   |                 +--> Task 4: Rename-collision guard + tri-state
   |                 |            chart_rename_status + move-to-_needs_review/
   |                 |            (same-volume/cross-volume-aware, manifest-logged)
   |                 |       |
   |                 |       +--> [resolve open question] --> Task 5: CLI wiring
   |                 |             (--scan-chart-names, --dry-run)
   |
   +--> Task 6: chorus_client.py — search_by_artist_title(), built from Bridge's
   |            source, shared module  [GATE]
           |
           +--> Track B: Chorus Metadata Enrichment
           |       Task 7: sanitize_chorus_field() + multi-key blank-only song.ini patch
           |          |
           |          +--> [resolve open question] --> Task 8: fill_song_ini_metadata()
           |          |     + enrich_song_ini_metadata_library() (per-item logging +
           |          |     aggregate summary) + confidence threshold
           |          |
           |          +--> Task 9: CLI wiring (--enrich-metadata, --dry-run)
           |
           +--> Track C: Duplicate Detection
                   Task 10: Duplicate-count estimate (fuzzy-match-only pass, no
                            fingerprinting) — sizes the rest of this track, and
                            covers the real dup2/dup253/dup2-4 cases found above
                      |
                      +--> Task 11: Fuzzy candidate grouping (negative case: Live/Acoustic/Remix)
                             |
                             +--> Task 11b: fpcalc/pyacoustid + confirm_group() fingerprinting
                             |              (official AcoustID/Chromaprint release only;
                             |              evaluate whether Chorus hash fields reduce this need)
                             |
                             +--> [resolve open question] --> Task 12: Scoring function
                             |     + weights, HARD-EXCLUDING needs_review/unscanned
                             |     folders from keeper selection — depends on Task 4's
                             |     chart_rename_status field
                             |
                             +--> [resolve open question] --> Task 13: Same-volume/
                                   cross-volume-aware move to _duplicates_review +
                                   destination verification before source removal +
                                   manifest logging + resumability + borrow-candidate
                                   flagging
                                    |
                                    +--> Task 14: CLI wiring (dedupe_report.py, --dry-run)

Phase 5 — Offset Feature Follow-Up (depends on Track C, specifically Task 14):
   Task 15: Confirm the real scope of the duplicate-blocker (which songs, how many
            copies each, whether any copy already has a settled video_start_time)
      |
      +--> Task 16: Re-run tasks/todo.md's offset-feature Task 12 playtest against
                    a deduped/unambiguous song, close out that long-pending item

Task 17: README updates (all three features) — after Tasks 5, 9, 14
Task 18: Real-library validation, all three in sequence — deferred to the user
```

Track A (chart rename) has no dependency on Task 0/6 and can be built and shipped independently first. Tracks B and C both depend on Task 6 but not on each other, so they can proceed in parallel once Task 6 lands — except Task 12, which now has a **hard** dependency on Track A's Task 4 for the `chart_rename_status` field (upgraded from "soft" per the bridge briefing). Phase 5 depends on Track C completing (specifically Task 14) since it's the dedupe pass that unblocks the offset feature's playtest.

## Recommended Sequencing

1. **Task 0** (read Bridge's source) can run in parallel with Track A — it blocks nothing in Track A. It is no longer open-ended browser reverse-engineering: the real host is already confirmed (`api.enchor.us`), so this task is specifically "read Bridge's client code for the request/response schema," with browser interception only as a time-boxed (~30 min) fallback if Bridge's source doesn't cover it.
2. **Track A (chart rename) ships first.** It's the cheapest (no new external dependency, no unresolved API question) and its output (`chart_rename_status` in `video_meta.json`) is a hard input to Track C's scoring — landing it first means Track C isn't guessing at the field shape.
3. **Task 6 (`chorus_client.py`)** lands once Task 0 resolves. Build it once, against Bridge's real schema, shared by both downstream tracks.
4. **Tracks B and C proceed in parallel** after Task 6, with Task 12 hard-depending on Track A's Task 4.
5. **Phase 5 (offset feature follow-up) runs as soon as Track C (Task 14) lands** — placed here rather than at the very end because it directly unblocks a long-pending item on the *other* feature's todo list, and there's no reason to make the user wait through Phase 6's docs/full-validation work before getting that resolved.
6. **Phase 6 (README + full real-library validation)** runs last, after all three CLI entry points exist and Phase 5 has closed the offset-feature loop — matches the existing project's pattern of deferring real-library/in-game verification to a human checkpoint (see `tasks/todo.md` Task 12 for the original precedent).

Every open question flagged below is meant to be resolved (a real decision made and written down) **before** the task immediately following it starts — that's why each is inserted directly above its related task rather than left in a spec's trailing "Open Questions" section.

## Phase 0 — Foundation Gate

- [x] **Task 0**: Read Bridge's (Geomitron) source for the real `api.enchor.us` request/response schema (S) — done 2026-07-14, via `git clone --depth 1 https://github.com/Geomitron/Bridge` and reading `search.service.ts`/`search.interface.ts` directly (much more reliable than the earlier browser-interception attempts, which had failed silently)
  - Confirmed: base URL `https://api.enchor.us` (matches Bridge's own `environment.prod.ts`). Real endpoint for artist/title lookups is `POST /search/advanced` with a structured body (every `AdvancedSearchSchema` field present, nullable defaults) — NOT a `GET .../search?query=` as the dead README implied, which explains why earlier browser GET attempts returned nothing.
  - Real response fields confirmed: `name`/`artist`/`album`/`genre`/`year`/`charter` (exactly what both specs already planned to fill/use) plus `chartId`, `md5`, `chartHash`, `song_length`, `diff_*`, `folderIssues`/`metadataIssues`, `modifiedTime`, `hasVideoBackground`. **No album-art field of any kind** (only an `albumArtMd5` hash, no URL/binary) — further confirms album art is out of scope.
  - **Correction found**: `SPEC-duplicate-detection.md`'s scoring design assumed a `chorus_data.get("upvotes", 0)` rating signal that does not exist in the real schema — flagged and corrected in that spec; Task 12 must re-scope this signal (chart-quality via `folderIssues`/`metadataIssues`, or drop the category).
  - Files: `SPEC-chorus-metadata.md`, `SPEC-duplicate-detection.md` (both updated with the real schema and the upvotes correction)

**Checkpoint 0 ✅**: real request/response schema documented in writing, sourced directly from Bridge's actual source, before Task 6 starts.

## Phase 1 — Track A: Chart Rename

- [ ] **Task 1**: ID-suffix detection for `song.ini`/`notes.chart`/`notes.mid` (S)
  - Acceptance: `scan_song_folder_chart_names()` correctly classifies synthetic fixtures — canonical names (`ok`), ID-suffixed names (flagged for further verification), no `.ini` at all (`no_ini`).
  - Verify: `pytest tests/test_chart_rename_detection.py -v`
  - Files: `clonehero_video_offset.py` (or new module), `tests/test_chart_rename_detection.py`

- [ ] **Task 2**: `.chart` Name/Artist fuzzy verification at the ≥85 threshold (S)
  - Acceptance: `verify_chart_content_match()` correctly matches real-shaped fixtures at the fixed 85 threshold and correctly rejects the real negative case (chart says "Rock & Roll Feeling", `song.ini` says "Mr. Roboto").
  - Verify: `pytest tests/test_chart_content_verification.py -v`
  - Files: same module, `tests/test_chart_content_verification.py`

- [ ] **Task 3**: `.mid` duration-vs-`song_length` fallback at ±2000ms (S)
  - Acceptance: mocked-`ffprobe` fixtures for matching/mismatching/missing-data duration comparisons all classify correctly at the fixed tolerance.
  - Verify: `pytest tests/test_chart_rename_mid_duration.py -v`
  - Files: same module, `tests/test_chart_rename_mid_duration.py`

> **RESOLVED** (real census run before Task 3b started): of 5,130 real library folders, 1,083 (~21%) are missing a literal `song.*` audio file with only ID-suffixed candidates; of those, 250 (~5% of the library) have multiple candidates and correctly route to `needs_review`, ~833 have exactly one and are safe to auto-rename. Common enough to matter, three-way classification sized correctly — no design change, proceeding with Task 3b as speced. Full writeup in `SPEC-chart-rename.md`'s Open Questions.

- [ ] **Task 3b**: Audio-stem naming check per role (S)
  - Acceptance: `scan_song_folder_audio_stems()` classifies each recognized stem role — the complete reserved set (`preview`/`song`/`guitar`/`rhythm`/`bass`/`keys`/`drums` or `drums_1`-`drums_4`/`vocals` or `vocals_1`/`vocals_2`/`vocals_explicit`/`vocals_explicit_1`/`vocals_explicit_2`/`crowd`) — as literal-match (`ok`), exactly-one-ID-suffixed-candidate (rename candidate), or multiple/conflicting candidates (`needs_review`, never auto-picked). Verified against the real Kryptonite fixture (four guitar candidates, two conflicting drum-mixing conventions) as the negative case.
  - Verify: `pytest tests/test_chart_rename_audio_ambiguity.py -v`
  - Files: same module, `tests/test_chart_rename_audio_ambiguity.py`

- [ ] **Task 3c**: Album-art naming check + `.sng` guard (S)
  - Acceptance: `scan_song_folder_album_art()` applies the same three-way classification to `album.png`/`album.jpg`/`album.jpeg`, with zero candidates as a valid non-blocking `ok` (album art isn't hard-required). Verified against the real Kryptonite/Mr. Roboto/You Only Live Once fixtures (all three have ID-suffixed album art alongside their known chart/audio issues). `is_sng_packaged()` causes every check in this track to skip a folder entirely when a `.sng` file is present.
  - Verify: `pytest tests/test_chart_rename_album_art.py tests/test_chart_rename_sng_guard.py -v`
  - Files: same module, both test files

**Checkpoint 1**: detection + all four verification paths (`.chart`, `.mid`, audio-stems, album-art) unit-tested green at the fixed thresholds, plus the `.sng` guard (no open threshold decisions remain).

- [ ] **Task 4**: Rename-collision guard + tri-state `chart_rename_status` + move-to-`_needs_review/` (M)
  - Acceptance: confirmed-match folders rename atomically; a pre-existing canonical-named file blocks the rename and relocates instead (never overwrites); unconfirmed folders — including any folder that fails the Task 3b audio-stem check or the Task 3c album-art check — are relocated intact to `_needs_review/` using same-volume/cross-volume-aware move logic (destination verified complete before source removal on cross-volume) and logged to a manifest; `chart_rename_status` is only `confirmed_ok` when the ini/chart/mid check, the audio-stem check, AND the album-art check all pass (or the folder is `.sng`-guarded and skipped); persists so reruns skip resolved folders; `--dry-run` touches zero files.
  - Verify: `pytest tests/test_chart_rename_collision.py tests/test_chart_rename_apply.py -v`
  - Files: same module, both test files

> **RESOLVED**: separate opt-in `--scan-chart-names` flag, not folded into the automatic startup video scan. Chart-rename relocates whole folders (more invasive than the video scan's in-place renames) and is freshly built — opt-in is the safer default (Rule 4), matching `--enrich-metadata`/`dedupe_report.py`'s own conventions. Can fold into the default scan later once proven reliable against the real library.

- [ ] **Task 5**: CLI wiring — `--scan-chart-names`, `--dry-run` (S)
  - Acceptance: flag documented and functional per the decision above, reflected in `README.md`.
  - Verify: manual run against a real library copy
  - Files: `CH-VideoScript.py`, `README.md`

**Checkpoint 2**: `pytest tests/ -v` green; dry-run against a copy of `M:\_organized\Test` identifies the 3 known 2026-07-12 `.ini`/`.chart`/`.mid` cases (2 relocated for content mismatch) AND correctly flags Kryptonite's audio-stem ambiguity AND all three affected folders' ID-suffixed album art — Kryptonite is expected to land in `_needs_review/` for the audio reason, not come out fully `confirmed_ok`.

## Phase 2 — Shared Foundation

- [ ] **Task 6**: `chorus_client.py` — `search_by_artist_title()`, built from Bridge's schema, shared module (M)
  - Acceptance: built against the Task 0-confirmed real schema; catches and logs network/lookup failures; returns `None` on no-match or error; never raises. Consumed identically by Tracks B and C — no second HTTP client introduced.
  - Verify: `pytest tests/test_chorus_client.py -v` (mocked HTTP) + one real manual call logged in the task notes
  - Files: `chorus_client.py`, `tests/test_chorus_client.py`, `pip-install.txt`

**Checkpoint 3**: `chorus_client.py` unit tests green; real API call confirmed working against the Bridge-sourced schema; module has no feature-specific logic in it (both downstream tracks import it unmodified).

## Phase 3 — Track B: Chorus Metadata Enrichment

- [ ] **Task 7**: `sanitize_chorus_field()` + multi-key blank-only `song.ini` patch function (M)
  - Acceptance: sanitizer rejects control characters, embedded `[`/`]`/`;`/`#`, embedded newlines, invalid UTF-8, and oversized values, never partially cleaning a value; patch function generalizes `patch_song_ini()`'s regex + atomic-write approach to fill `{year, genre, charter, album}` with only sanitizer-approved values; existing values are never touched (byte-identical for already-populated keys); CRLF/LF and unrelated-line preservation hold.
  - Verify: `pytest tests/test_chorus_field_sanitization.py tests/test_metadata_ini_patch.py -v`
  - Files: `CH-VideoScript.py` (or new module), both test files

> **RESOLVED**: field list stays `year`/`genre`/`charter`/`album` — no reason to widen, and all four are confirmed real response fields (Task 0). Match-confidence threshold: **70** (`SequenceMatcher` ratio*100 on normalized name+artist, both must clear it — reusing the same `normalize_lookup_value`/`SequenceMatcher` pattern already in the project). Set lower than chart-rename's 85 because a wrong metadata fill (a slightly-off genre/year) is far less destructive than a bad file rename — matches the project's existing "70-89: high confidence" band for the YouTube-match use case, a comparably low-stakes decision.

- [ ] **Task 8**: `fill_song_ini_metadata()` + `enrich_song_ini_metadata_library()` (per-item logging + aggregate summary) + confidence threshold (M)
  - Acceptance: every song's outcome (`filled`/`no_change`/`no_match`/`error`) is logged with a reason; an aggregate summary prints at the end of a library run, mirroring `scan_and_fix_video_library()`'s/`scan_and_fix_chart_library()`'s reporting contract; confidence threshold decided above is implemented as written.
  - Verify: `pytest tests/test_chorus_metadata_fill.py tests/test_chorus_lookup_confidence.py -v`
  - Files: same module, both test files

- [ ] **Task 9**: CLI wiring — `--enrich-metadata`, `--dry-run` (S)
  - Acceptance: flag documented and functional.
  - Verify: manual dry-run against a real library sample; inspect proposed fills for plausibility
  - Files: `CH-VideoScript.py`, `README.md`

**Checkpoint 4**: `pytest tests/ -v` green; dry-run against a real sample shows plausible fills; zero existing `song.ini` fields altered; per-song log + aggregate summary confirmed present.

## Phase 4 — Track C: Duplicate Detection

- [x] **Task 10**: Duplicate-count estimate — fuzzy-match-only pass, no fingerprinting (S)
  - **Done 2026-07-14.** First pass (exact-normalized-key grouping via existing `parse_folder_name`/`normalize_lookup_value`) found only 27 groups/54 folders -- undercounted because it missed the known real `[dup2]`/`[dup253]` cases entirely (the existing `strip_title_noise` regexes don't strip bracket-suffix noise like `[dup253]`, only trailing parenthetical noise). Added a `[dupN]`/trailing-bracket strip before normalizing and re-ran: **336 candidate duplicate groups, 844 folders total (~16.5% of the 5,130-song library)** -- distribution: 226 groups of 2, 66 of 3, 29 of 4, 13 of 5, 1 of 6, 1 of 7. All three previously-confirmed real cases (`I Write Sins Not Tragedies`, `Snow (Hey Oh)`, `My Name Is Jonas`) correctly appear. This is common enough to matter, not a rare edge case -- confirms the feature's real value, and confirms Task 11's real fuzzy-matching grouper needs to handle bracket-noise suffixes as a known real pattern, not just typos/case differences.
  - Verify: manual run, count recorded above
  - Files: none (throwaway script; reused in Task 11's real grouping implementation)

- [ ] **Task 11**: Fuzzy candidate grouping (M)
  - Acceptance: reuses `SequenceMatcher`/`normalize_lookup_value` matching already in `CH-VideoScript.py`; the negative case (same title, "Live"/"Acoustic"/"Remix" tag) is never auto-grouped by fuzzy match alone.
  - Verify: `pytest tests/test_dedupe_grouping.py -v`
  - Files: `dedupe_report.py`, `tests/test_dedupe_grouping.py`

- [ ] **Task 11b**: `fpcalc`/`pyacoustid` (official release) setup + `confirm_group()` fingerprinting (M)
  - Acceptance: candidate groups are narrowed to fingerprint-confirmed duplicates only; unit tests use canned `fpcalc` output, no real audio decode required; a documented decision on whether Chorus hash fields reduce reliance on this.
  - Verify: `pytest tests/test_dedupe_fingerprint.py -v`
  - Files: `dedupe_report.py`, `tests/test_dedupe_fingerprint.py`, `pip-install.txt`, `README.md` (fpcalc install + trusted-source note)

> **RESOLVED**: concrete weights proposed and recorded in the spec's Code Style section — `instrument_count` (5/diff key, max 65) dominates as the actual playable-content signal; `has_video` (10), `offset_confidence` (max 10), `metadata_completeness` (2/key, max 8), and the re-scoped `chorus_signal` (5, based on absence of `folderIssues`/`metadataIssues` rather than the nonexistent "upvotes") are smaller supplementary signals. Max possible score ~98.

- [ ] **Task 12**: Scoring function + weights, **hard-excluding `needs_review`/unscanned folders from keeper selection** (M)
  - Acceptance: scoring signals implemented per the weights decided above; **`select_keeper()` asserts keeper-eligibility (`chart_rename_status == "confirmed_ok"`) as a hard precondition, not a soft check — if every folder in a group is `needs_review` or unscanned, the whole group is skipped and flagged for manual attention instead of auto-resolved.**
  - Verify: `pytest tests/test_dedupe_scoring.py -v`, including the all-`needs_review`/unscanned-group fixture
  - Files: `dedupe_scoring.py`, `tests/test_dedupe_scoring.py`

> **RESOLVED**: flat structure, `[dupN]` suffix on name collision — reusing the exact same, already-shipped-and-tested pattern `move_to_needs_review()` (`clonehero_video_offset.py`, Task 4) uses for `_needs_review/`, for cross-feature consistency and because it's a proven mechanism, not a new design.

- [ ] **Task 13**: Same-volume/cross-volume-aware move to `_duplicates_review`, manifest logging, resumability, borrow-candidate flagging (M)
  - Acceptance: same-volume moves use direct atomic rename; cross-volume moves verify destination completeness (size/count or checksum) before removing the source; every move (either case) is logged to a manifest (source, destination, score, reason, volume-crossing, verification result); already-resolved groups are skipped on rerun; borrow-candidate flags logged only, never acted on; `--dry-run` touches zero files; collision strategy from above is implemented.
  - Verify: `pytest tests/test_dedupe_move.py tests/test_borrow_candidates.py -v`, including a simulated-interrupted-cross-volume-move test
  - Files: `dedupe_report.py`, both test files

- [ ] **Task 14**: CLI wiring — `dedupe_report.py --dry-run`, `--library-path` (S)
  - Acceptance: entry point functional and documented.
  - Verify: manual dry-run against a real library sample
  - Files: `dedupe_report.py`, `README.md`

**Checkpoint 5**: `pytest tests/ -v` green (full suite, all tracks); dry-run against the real library produces groups with zero known false positives on a manually spot-checked sample; confirmed zero `needs_review`/unscanned folders were auto-selected as a keeper; manifest correctly logs every planned move; the real `[dup2]`/`[dup253]`/`[dup2-4]` groups resolve to a single keeper each.

## Phase 5 — Offset Feature Follow-Up

This phase exists specifically to unblock `tasks/todo.md`'s long-pending Task 12 (in-game playtest for the offset feature), which turned out to be blocked by exactly the problem Track C solves — see Context above. Placed here, right after Track C, rather than at the end, since there's no reason to make the user wait through Phase 6's docs/full-validation pass before this gets resolved.

- [x] **Task 15**: Confirm the real scope of the duplicate-blocker (S)
  - **Done 2026-07-14.** Real copy counts (from Task 10's census): `Helena` — 1 copy, no duplicate at all (was never actually part of the blocker). `I Write Sins Not Tragedies` — 2 copies. `Snow (Hey Oh)` — 2 copies. `My Name Is Jonas` — 4 copies. **None of the 8 duplicate copies (nor `Helena`) has a `video_meta.json` in the real library at all** — the offset feature has never been run against `M:\_Organized\Songs` for any of these songs, only against the small `M:\_organized\Test` staging copies. There's nothing to "resume" or conflict with; Task 16 just needs one clean copy picked and the offset feature run fresh against it.
  - Verify: manual inspection via direct file check, recorded above
  - Files: none (investigation task)

- [ ] **Task 16 — YOURS TO RUN**: Re-run the offset feature's Task 12 playtest against a deduped/unambiguous song (S)
  - Acceptance: pick one clean copy of `I Write Sins Not Tragedies`, `Snow (Hey Oh)`, or `My Name Is Jonas` (dedupe once `fpcalc` is installed and you've run `dedupe_report.py` for real, or just pick one copy by hand right now — nothing is resolved automatically yet), run `python CH-VideoScript.py` against it to compute+write an offset, then load it in Clone Hero and confirm the video syncs — the actual acceptance bar `tasks/todo.md`'s Task 12 has been waiting on.
  - Verify: manual in-game check
  - Files: `tasks/todo.md` (mark Task 12 resolved with the result)

**Checkpoint 6**: the offset feature's `tasks/todo.md` Task 12 is finally closed out, with a real, unambiguous song confirmed synced in-game.

## Phase 6 — Integration

- [ ] **Task 17**: README updates across all three features, plus a short cross-feature glossary (S)
  - Acceptance: `--scan-chart-names`, `--enrich-metadata`, and `dedupe_report.py` are all documented with the same clarity as the existing offset-detection section; a short "which tool did what, and what do I do about each outcome" section reconciles the three different attention-needed vocabularies (`_needs_review/`, `_duplicates_review/`+borrow-candidates, silent-vs-logged metadata skips) into one place.
  - Verify: manual read-through
  - Files: `README.md`

- [ ] **Task 18: Real-library validation — YOURS TO RUN** (deferred to the user, matches `tasks/todo.md` Task 12 precedent)
  - Run chart-rename, then metadata enrichment, then dedupe (in that order) against the real library — or a copy of it first, per your comfort level
  - Confirm: the 3 known 2026-07-12 chart-rename cases resolve as expected; a handful of enriched `song.ini` files look right; at least one duplicate group's keeper pick looks right before deleting anything from `_duplicates_review`
  - Report back: what ran, what you found, anything that looked wrong

## Notes

- This plan does not touch or re-open `tasks/plan.md` (the offset feature's original plan) — it does touch `tasks/todo.md`'s Task 12 in Phase 5, since that's the item this plan's new phase directly resolves.
- The `needs_review`-exclusion requirement in Task 12 is now a hard requirement (upgraded from this plan's original "soft dependency" framing) per the 2026-07-13 bridge briefing — see Context above.
- Every open question called out with a `> **Resolve first**` block is meant to block its following task from starting, not just be noted and skipped past.
- No task should require changing more than ~5 files; tasks are ordered by dependency, not perceived importance, per the spec-driven-development skill's task template.

## Someday / Backlog

- **Desktop GUI (punk rock aesthetic)** — not scoped or spec'd yet; would need its own `SPEC-desktop-gui.md` before planning (see [workflow-ordering](../../../.claude/rules/workflow-ordering.md): spec before plan). Full recommendation from the 2026-07-13 discussion, kept here for when this gets picked up:

  **Goal**: move `CH-VideoScript.py` (currently `argparse`-driven) off the terminal into a windowed app — professional-looking, punk rock aesthetic, intuitive controls (buttons/progress bars instead of flags) over the existing library-scan/offset/rename/dedupe functions.

  **Two paths considered:**
  1. **PySide6/PyQt6 (native Python desktop)** — wrap the existing functions directly, no separate backend process. QSS stylesheets give full control over a punk look (distressed fonts, high-contrast black/red, custom icons); packages to a single `.exe` via PyInstaller. Lower effort since it stays in the current codebase/dependency chain. Main risk: downloads/scans must run off the UI thread (`QThread`) or the window freezes.
  2. **Web frontend (HTML/CSS/JS) + Tauri or Electron shell**, with the script exposed as a local FastAPI backend — higher aesthetic ceiling (CSS handles textures/grain/animation more easily than QSS), but more moving parts: a second process, an IPC/HTTP layer, more to package and debug for what's currently a single script.

  **Recommendation: go with PySide6 (option 1)** for a personal tool — the web+shell route only pays off if the visual polish ceiling of QSS turns out to be the actual blocker, which is unlikely for a punk aesthetic (grunge/high-contrast styles are very achievable in QSS + custom fonts).

  **Tools/agents to use when this gets built:**
  - `senior-frontend` skill/agent — only if path 2 (web) is chosen instead.
  - `frontend-ui-engineering` skill — layout/component polish for either path.
  - `debugger` agent — for `QThread`/threading issues when wiring downloads and long-running scans to the UI without freezing it.
  - `canvas-design` skill (re-enabled 2026-07-13 specifically for this) and/or **Canva MCP** (already connected) — generate actual punk-rock visual assets (app icon, splash screen, background textures/grain) as PNGs to embed via `QIcon`/`QPixmap`, rather than approximating the look in code alone.
  - Skip `theme-factory` and `frontend-design` — the former targets artifacts/docs theming (not QSS), the latter generates web component code that doesn't transfer to Qt.

- **Artist name normalization** — not scoped or spec'd yet; would need its own `SPEC-artist-normalization.md` before planning.

  **Goal**: collapse capitalization/punctuation/spelling variants of the same artist in `song.ini`'s `artist` field (and wherever else it's used for grouping/display) — e.g. three different-cased/punctuated copies of "Panic! At The Disco" should normalize to one canonical form.

  **Critical caution (from the user, 2026-07-13): do not over-merge similarly-named but genuinely distinct acts.** Example given: Sublime and Sublime with Rome are related but different groups and must NOT be collapsed into one canonical artist — a naive fuzzy-match/normalize pass would wrongly merge them. Any matching approach needs an explicit "known distinct act" guard or a conservative-enough threshold that this class of case doesn't get merged. Worth testing against this exact pair (and similar cases — bands with "reunion"/spin-off/tribute variants) as a required negative-case fixture, the same way `SPEC-duplicate-detection.md`'s Task 11 already treats "Live"/"Acoustic"/"Remix" as a negative case for fuzzy grouping.

  **Relationship to existing work**: this overlaps conceptually with Track C (Duplicate Detection) above, which already does fuzzy artist/title matching (`SequenceMatcher`/`normalize_lookup_value`) for finding duplicate *songs*. Artist normalization is a related but distinct problem (same artist, different string — not necessarily the same song), and whether it should be a new module, a variant pass in `dedupe_report.py`, or a shared normalization layer both features draw from is an open design question for whenever this gets spec'd.
