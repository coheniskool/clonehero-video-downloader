# Todo: Video Offset Calculator

See [plan.md](plan.md) for full task descriptions, acceptance criteria, and verification steps.

## Phase 0 — Reconcile
- [ ] Task 1: Update SPEC.md to reflect decisions made during planning (S)
- [ ] Task 2: Remove the dead standalone batch_process()/CLI entry point (XS)

**Checkpoint 1**: smoke import succeeds; SPEC.md matches plan direction

## Phase 1 — Foundation fixes
- [ ] Task 3: Glob-based file discovery, ID-suffix aware (S)
- [ ] Task 4: Byte-preserving, atomic song.ini patch scoped to video_start_time only (M)

**Checkpoint 2**: `pytest tests/ -v` green; manual song.ini diff shows only video_start_time changed

## Phase 2 — Correlation backend swap
- [ ] Task 5: Swap correlation backend to audio-offset-finder (M)
- [ ] Task 6: Sign-convention verification test — GATE, do not skip (M)

**Checkpoint 3 — hard gate**: sign test passing before any further write-path work

## Phase 3 — VFR handling
- [ ] Task 7: VFR detection and CFR re-encode (M)

## Phase 4 — Resumability + reporting
- [ ] Task 8: video_meta.json offset fields + resumability (M)
- [ ] Task 9: scores.bin research spike, timeboxed ~2hrs (S)

**Checkpoint 4**: tests green; ffmpeg/ffprobe confirmed; spike outcome documented

- [ ] Task 10: Library status report generator (M)

## Phase 5 — Wire up + validate
- [ ] Task 11: --dry-run wired end-to-end (S)

**Checkpoint 5**: full suite green; dry-run touches zero files; report inspected

- [ ] Task 12: Real-library validation + in-game playtest (S)
- [ ] Task 13: Docs update (XS)

## Notes
- Biggest risk: `audio-offset-finder` may not install cleanly on Windows — check first thing in Task 5.
- Task 6 is a hard gate — do not proceed past it if the sign test fails or is skipped.
- Task 9 is timeboxed — do not let it expand without checking back in.
