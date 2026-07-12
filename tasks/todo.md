# Todo: Video Offset Calculator

See [plan.md](plan.md) for full task descriptions, acceptance criteria, and verification steps.

## Phase 0 — Reconcile
- [x] Task 1: Update SPEC.md to reflect decisions made during planning (S)
- [x] Task 2: Remove the dead standalone batch_process()/CLI entry point (XS)

**Checkpoint 1**: smoke import succeeds; SPEC.md matches plan direction ✅

## Phase 1 — Foundation fixes
- [x] Task 3: Glob-based file discovery, ID-suffix aware (S)
- [x] Task 4: Byte-preserving, atomic song.ini patch scoped to video_start_time only (M)

**Checkpoint 2**: `pytest tests/ -v` green; manual song.ini diff shows only video_start_time changed ✅

## Phase 2 — Correlation backend swap
- [x] Task 5: Swap correlation backend to audio-offset-finder (M)
- [x] Task 6: Sign-convention verification test — GATE, do not skip (M)

**Checkpoint 3 — hard gate**: sign test passing before any further write-path work ✅

## Phase 3 — VFR handling
- [x] Task 7: VFR detection and CFR re-encode (M)

## Phase 4 — Resumability + reporting
- [x] Task 8: video_meta.json offset fields + resumability (M)
- [x] Task 9: scores.bin research spike, timeboxed ~2hrs (S) — outcome: no-go, CH-score column always shows "unknown"

**Checkpoint 4**: tests green; ffmpeg/ffprobe confirmed; spike outcome documented ✅

- [x] Task 10: Library status report generator (M)

## Phase 5 — Wire up + validate
- [x] Task 11: --dry-run wired end-to-end (S)

**Checkpoint 5**: full suite green (65 tests); dry-run touches zero files (verified with a real, non-mocked run); report inspected ✅

- [ ] **Task 12: Real-library validation + in-game playtest (S) — YOURS TO RUN**
  - Run `python CH-VideoScript.py` (or `--dry-run` first to preview) against real songs
  - Load a processed song in Clone Hero, confirm the video syncs
  - Real dry-run data point already gathered: "3 Doors Down - Kryptonite" computed `video_start_time = 816ms` at confidence `2.40` (notably lower than the ~8.8 synthetic-signal benchmark) — worth playtesting first to check both correctness and whether `MIN_STANDARD_SCORE` needs recalibrating
  - Report back: song(s) tested, `video_start_time` written, synced or not
- [x] Task 13: Docs update (XS)

## Notes
- Biggest risk (`audio-offset-finder` on Windows) materialized and was resolved: required pinning `numpy>=2,<=2.4` (see pip-install.txt and clonehero_video_offset.py header comment).
- Task 6's gate passed — sign convention verified against real ffmpeg-injected delays, both directions.
- Task 9 concluded within its timebox — see SPEC.md Open Questions for the full writeup.
- All 65 tests passing as of Task 13. `git log` has one commit per task.
