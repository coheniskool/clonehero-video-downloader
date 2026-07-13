# Todo: Chart Rename + Chorus Metadata Enrichment + Duplicate Detection

See [plan-next-features.md](plan-next-features.md) for full task descriptions, acceptance criteria, and verification steps. Touches [todo.md](todo.md)'s Task 12 in Phase 5 below (that's the item this plan's new phase resolves) but does not otherwise touch [plan.md](plan.md).

**2026-07-13**: bridge briefing conducted (`.bridge/briefings/2026-07-13-next-features-plan-review.md`, unanimous ENGAGE WITH CAUTION). Six must-fix items folded into the tasks below — see plan's Context section for the full list.

**2026-07-13 follow-up**: verified against the official Clone Hero Wiki + the real library — the "audio stems don't need touching" assumption in `SPEC-chart-rename.md` was wrong (no documented tolerance for ID-suffixed audio; the spec's own "safe" Kryptonite example has zero literal-named audio files and genuinely ambiguous/conflicting candidates). Confirmed by the user: Kryptonite produces no audio in Clone Hero today. Added Task 3b below.

**2026-07-13 second follow-up**: the user tried to playtest a different Test-folder song instead of Kryptonite and hit the same class of problem from another angle — those songs are "stuck as duplicates." Confirmed real in the live library: `Panic! At The Disco - I Write Sins Not Tragedies [dup2]`, `Red Hot Chili Peppers - Snow (Hey Oh) [dup253]`, `Weezer - My Name Is Jonas [dup2/dup3/dup4]` all exist. This is the exact problem `SPEC-duplicate-detection.md` solves — added Phase 5 below, sequenced right after Track C (not at the end) since it unblocks a long-pending item on the offset feature's own todo list.

**2026-07-14 final-review follow-up**: verified against the official wiki once more before `/build` — found album art (`album.png`/`.jpg`) is also a required-literal-filename item, missed entirely in the original scope. Every ID-suffixed-chart folder found so far also has ID-suffixed album art. Added Task 3c. Also corrected the audio-stem role list to the complete authoritative set (was missing `preview` and the `vocals_*` variants) and added a defensive `.sng`-container skip guard.

Every open question below is meant to be resolved **before** the task immediately following it — inserted inline rather than left in a spec's trailing Open Questions section.

## Phase 0 — Foundation Gate
- [x] Task 0: Read Bridge's (Geomitron) source for the real api.enchor.us schema (S) — done via `git clone` + reading `search.service.ts`/`search.interface.ts` directly. Real endpoint: `POST /search/advanced`, not GET. Real fields confirmed (name/artist/album/genre/year/charter + more), no album-art field at all. Found and corrected a real bug: dedupe's scoring design assumed a nonexistent "upvotes" field — flagged for Task 12 re-scoping.

**Checkpoint 0 ✅**: real request/response schema documented in both specs, sourced from Bridge's actual source.

## Phase 1 — Track A: Chart Rename (no dependency on Task 0)
- [x] Task 1: ID-suffix detection for song.ini/notes.chart/notes.mid (S) — `scan_song_folder_chart_names()`, commit ea5920d
- [x] Task 2: .chart Name/Artist fuzzy verification at >=85 threshold, incl. real Mr. Roboto negative case (S) — `verify_chart_content_match()`, commit b653671
- [x] Task 3: .mid duration-vs-song_length fallback at +/-2000ms (S) — `probe_audio_duration_ms()`, commit b75d03e

> **RESOLVED**: real census (5,130 folders) — 1,083 (~21%) missing literal song.*, 250 (~5%) with multiple candidates. Common enough to matter, three-way design confirmed correct, no change needed.

- [x] Task 3b: Audio-stem naming check per role (complete set: preview/song/guitar/rhythm/bass/keys/drums(_1-4)/vocals(_1/_2/_explicit(_1/_2))/crowd) — literal/rename-candidate/multiple-candidates classification, verified against the real Kryptonite negative case (four guitar files, conflicting drum conventions) (S) — `scan_song_folder_audio_stems()`, commit d40ba17
- [x] Task 3c: Album-art naming check (album.png/.jpg/.jpeg, zero candidates OK) + `.sng`-container skip guard, verified against real Kryptonite/Mr. Roboto/You Only Live Once album-art fixtures (S) — `scan_song_folder_album_art()`/`is_sng_packaged()`, commit 75451a0

**Checkpoint 1 ✅**: detection + all four verification paths (.chart/.mid/audio-stems/album-art) unit-tested green at the fixed thresholds, plus the .sng guard — no open threshold decisions remain. 133 tests passing, no regressions.

- [ ] Task 4: Rename-collision guard + tri-state chart_rename_status (only confirmed_ok when ini/chart/mid AND audio-stem AND album-art checks all pass) + move-to-_needs_review/ (same-volume/cross-volume-aware, manifest-logged) (M)

> **RESOLVED**: separate opt-in `--scan-chart-names` flag, not folded into the automatic startup video scan. Chart-rename relocates whole folders out of the library (more invasive than the video scan's in-place file renames) and is freshly built/not yet battle-tested — opt-in is the safer default, matching `--enrich-metadata`/`dedupe_report.py`'s own separate-flag conventions. Can be folded into the default scan later once proven reliable.

- [x] Task 4: Rename-collision guard + tri-state chart_rename_status (only confirmed_ok when ini/chart/mid AND audio-stem AND album-art checks all pass) + move-to-_needs_review/ (same-volume/cross-volume-aware, manifest-logged) (M) — `process_chart_folder_names()`, `move_to_needs_review()`, `process_song_folder_for_chart_rename()`, commits 755a861, 3e0d7aa, 4aaa6c6
- [x] Task 5: CLI wiring — --scan-chart-names, --dry-run (S) — `scan_and_fix_chart_library()`, commit 00e3802

**Checkpoint 2 ✅**: 159 tests passing, no regressions. Verified end-to-end against a disposable copy of the real Test library: dry-run correctly flags Kryptonite's audio/album-art ambiguity and touches zero files (diff-confirmed); a real run relocates it intact to `_needs_review/` with a correct manifest entry; a second run is a no-op (resumability confirmed). **Phase 1 (Track A: Chart Rename) is complete.**

## Phase 2 — Shared Foundation
- [x] Task 6: chorus_client.py — search_by_artist_title(), built from Bridge's schema, shared by Tracks B & C (M) — commit 564ef5d, verified with a real live call against api.enchor.us

**Checkpoint 3 ✅**: chorus_client unit tests green (7/7); real API call confirmed working against the Bridge-sourced schema, response matches exactly. **Phase 2 complete.**

## Phase 3 — Track B: Chorus Metadata Enrichment (depends on Task 6)
- [x] Task 7: sanitize_chorus_field() + multi-key blank-only song.ini patch function (M) — commit 268063e

> **RESOLVED**: field list stays year/genre/charter/album (all confirmed real fields). Confidence threshold: 70 (SequenceMatcher on name+artist, weaker of the two scores).

- [x] Task 8: fill_song_ini_metadata() + enrich_song_ini_metadata_library() (per-item log + aggregate summary) + confidence threshold (M) — commit 0364ae1
- [x] Task 9: CLI wiring — --enrich-metadata, --dry-run (S) — commit 20f9ab0

**Checkpoint 4 ✅**: 198 tests passing. Verified end-to-end against the LIVE Chorus Encore API (not just mocked): dry-run against the real Test library correctly reports "no change" (already fully populated); a synthetic copy with genre/charter blanked gets them filled with real data; year/album (never blanked) confirmed untouched. **Phase 3 (Track B) complete.**

## Phase 4 — Track C: Duplicate Detection (depends on Task 6; Task 12 HARD-depends on Task 4)
- [x] Task 10: Duplicate-count estimate (S) — **336 candidate groups, 844 folders (~16.5% of library)**; found + fixed a real undercount bug (bracket-suffix noise like `[dup253]` wasn't being stripped before normalizing); all 3 known real cases confirmed caught
- [ ] Task 11: Fuzzy candidate grouping, incl. Live/Acoustic/Remix negative case (M)
- [ ] Task 11b: fpcalc/pyacoustid (official release only) + confirm_group() fingerprinting; evaluate Chorus hash fields as an alternative (M)

> **Resolve first**: exact scoring weights/formula, informed by Task 10's real count and the real dup2/dup253/dup2-4 examples.

- [ ] Task 12: Scoring function + weights — **hard-excludes needs_review/unscanned folders from keeper selection, asserted not just documented** (M)

> **Resolve first**: `_duplicates_review` folder-naming/collision strategy (flat vs. grouped-by-title subfolders).

- [ ] Task 13: Same-volume/cross-volume-aware move to _duplicates_review + destination verification before source removal + manifest logging + resumability + borrow-candidate flagging (M)
- [ ] Task 14: CLI wiring — dedupe_report.py --dry-run, --library-path (S)

**Checkpoint 5**: full suite green (all tracks); dry-run produces zero known false positives on a spot-checked sample; confirmed zero needs_review/unscanned folders auto-selected as a keeper; manifest correctly logs every planned move; the real dup2/dup253/dup2-4 groups resolve to a single keeper each.

## Phase 5 — Offset Feature Follow-Up (depends on Track C / Task 14)
Unblocks `tasks/todo.md`'s long-pending Task 12 — placed here, not at the end, since there's no reason to wait through Phase 6's docs pass for this.

- [ ] Task 15: Confirm the real scope of the duplicate-blocker (how many copies each of Helena/I Write Sins Not Tragedies/Snow (Hey Oh)/My Name Is Jonas has; whether any copy already has a settled offset) — can piggyback on Task 10's census (S)
- [ ] Task 16: Re-run the offset feature's Task 12 playtest against a deduped/unambiguous song; mark `tasks/todo.md` Task 12 resolved with the result (S)

**Checkpoint 6**: offset feature's Task 12 finally closed out with a real, unambiguous song confirmed synced in-game.

## Phase 6 — Integration
- [ ] Task 17: README updates across all three features + a cross-feature glossary reconciling the three different attention-needed vocabularies (S)
- [ ] **Task 18: Real-library validation — YOURS TO RUN**
  - Run chart-rename → metadata enrichment → dedupe, in that order, against real (or copied) library
  - Confirm the 3 known chart-rename cases resolve correctly, a sample of enriched song.ini files look right, and at least one dedupe keeper pick looks right before deleting anything
  - Report back what ran and what you found

## Notes
- Recommended build order: Track A first (no external blockers, and its chart_rename_status field is now a HARD input to Task 12) → Task 6 → Tracks B and C in parallel → Phase 5 (offset follow-up) → Phase 6 (integration).
- Six must-fix items from the 2026-07-13 bridge briefing are now built into the tasks above, not follow-ups — see plan-next-features.md's Context section for the full list and rationale.
- Every `> **Resolve first**` callout blocks the task immediately below it from starting.
