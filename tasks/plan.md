# Implementation Plan: Video Offset Calculator for clonehero-video-downloader

## Context

The user asked for a tool to compute and write Clone Hero's `video_start_time` offset automatically after a video downloads (`/spec` → `SPEC.md`, approved earlier this session). While that spec was being written, an **independent branch (`coheniskool-effective-giggle`) was fast-forward merged into `master` at 2026-07-11 14:33** (commit `b23a7e3`), adding a working-but-buggy offset-detection feature using **librosa + DTW** instead of the `audio-offset-finder`/MFCC approach the spec describes. `CH-VideoScript.py` grew from ~200 lines (what `/spec` was written against) to 1,208 lines in the process.

This was discovered and independently verified by reading the actual merged code during `/plan`, not assumed from a research agent's report. Confirmed, currently-live bugs in the merged code:
1. `find_song_audio()` (`clonehero_video_offset.py:40-47`) only matches exact filenames (`song.ogg`, `song.opus`, `song.mp3`, `song.wav`), falling back to "the only audio file in the folder" otherwise — silently returns nothing for the ID-suffixed half of the library (`song_1877.ogg`), confirmed against real folders in `M:\_Organized\Songs`.
2. `update_ini_with_offset()` (`CH-VideoScript.py:542-575`) matches whichever of `video_start_time`, `offset`, `song_offset`, `video_offset` it finds **first** in the file and overwrites that one — a real risk of silently clobbering a chart's actual `offset` key instead of `video_start_time`.
3. The DTW-derived offset's sign has never been verified against a known test case.
4. No resumability — `video_meta.json` only stores video-match confidence, not offset status, so a rerun recomputes every song's offset.
5. `clonehero_video_offset.py` also has a standalone `batch_process()`/`ThreadPoolExecutor` CLI entry point that's never called from `CH-VideoScript.py`'s `main()` — dead code that could race on the same `video_meta.json` files if ever run alongside the main flow.

**Decisions made with the user before planning further:**
- Replace the librosa/DTW correlation backend with `audio-offset-finder` (MFCC-based), per the original spec — not a hardening of the DTW code.
- Keep per-folder `video_meta.json` as the write-path source of truth (not a central CSV), but add a **new library-status report generator** the user explicitly asked for: a scan across all song folders producing a single reviewable file with, per song — has video? video confidence, has a Clone Hero score (best-effort; implies the user has played it, which is a decent proxy for "sync already manually confirmed"), offset confidence/status, and a needs-review flag.
- Remove the dead standalone `batch_process()` CLI entry point.
- Clone Hero's `scores.bin` (`AppData\LocalLow\srylain Inc_\Clone Hero\scores.bin`) was inspected directly: it's only 358 bytes and last modified **2022-06-08** — almost certainly stale relative to the current 5,131-song library, and it's an undocumented custom binary format. The "has a CH score" column is scoped as a **timeboxed research spike with a documented fallback** (show "unknown" and drop the column from later tasks if parsing isn't feasible in ~2 hours), not a hard requirement — it must not block the report generator shipping.

## Dependency graph

```
Task 1: Update SPEC.md to reflect the decisions above (doc only)
   |
   +--> Task 2: Remove dead batch_process()/CLI entry point
   |
   +--> Task 3: Glob-based file discovery (find_reference_audio/find_song_ini/find_video_file)
            |
            +--> Task 4: Byte-preserving atomic song.ini patch, scoped to video_start_time only
                     |
                     +--> Task 5: Swap compute_offset() to audio-offset-finder, remove DTW/librosa code
                              |
                              +--> Task 6: Sign-convention verification test  [GATE]
                                       |
                                       +--> Task 7: VFR detection + CFR re-encode
                                                |
                                                +--> Task 8: video_meta.json offset fields + resumability
                                                         |
                                                         +--> Task 9: scores.bin research spike (timeboxed)
                                                         |        |
                                                         +--------+--> Task 10: Library status report generator
                                                                           |
                                                                           +--> Task 11: --dry-run end-to-end
                                                                                    |
                                                                                    +--> Task 12: Real-library validation + in-game playtest
                                                                                             |
                                                                                             +--> Task 13: Docs update
```

Tasks 2 and 3 have no dependency on each other and can be done in either order; both must land before Task 4.

## Task List

### Task 1: Update SPEC.md to reflect decisions made during planning
**Description:** Correct `SPEC.md`'s Tech Stack, Project Structure, and Success Criteria sections to describe what will actually be built: `audio-offset-finder` (confirmed, not a change from the original spec), `video_meta.json`-based persistence plus the new library-status report generator (replacing the CSV-column success criteria), and the removal of the dead CLI entry point. Spec stays the living source of truth per spec-driven-development conventions — update it before code changes, not after.
**Acceptance criteria:**
- Tech Stack section names `audio-offset-finder`/`numpy` with no contradiction against `librosa` remaining anywhere in the doc.
- Success Criteria section describes the library-status report (fields: video present, video confidence, offset present, offset confidence/status, CH-score best-effort, needs-review flag) instead of the old CSV-column bullet.
- A line documents the `coheniskool-effective-giggle` merge and that this plan reconciles against it.
**Verification:** Manual review — every claim in `SPEC.md` should be checkable against a real file/line in the repo.
**Dependencies:** None.
**Files touched:** `SPEC.md`.
**Size:** S.

### Task 2: Remove the dead standalone batch_process()/CLI entry point
**Description:** Delete `batch_process()`, the `ThreadPoolExecutor` import, `argparse` CLI block, and the `if __name__ == "__main__":` block at the bottom of `clonehero_video_offset.py` — none of it is called from `CH-VideoScript.py`'s `main()`, and it's a race risk against the same `video_meta.json`/`song.ini` files if ever run in parallel with the real entry point.
**Acceptance criteria:**
- `clonehero_video_offset.py` no longer has a `__main__` block or CLI argument parsing.
- `CH-VideoScript.py`'s existing import (`from clonehero_video_offset import extract_audio, compute_offset, find_song_audio, find_video_file`) still works unchanged.
- `tqdm`/`ThreadPoolExecutor`/`argparse` imports are removed from `clonehero_video_offset.py` only if nothing else in the file uses them (check before deleting).
**Verification:** `python -c "import clonehero_video_offset"` succeeds; `python CH-VideoScript.py` still starts and reaches the confidence-threshold prompt without import errors.
**Dependencies:** None.
**Files touched:** `clonehero_video_offset.py`.
**Size:** XS.

### ✅ Checkpoint 1 (after Tasks 1–2)
- `python -c "import clonehero_video_offset, CH-VideoScript"`-style smoke import succeeds (adjust for the script's actual importability — it may need `python -m py_compile CH-VideoScript.py` instead since it's a `__main__`-oriented script).
- `SPEC.md` reviewed and matches the plan's stated direction.

### Task 3: Glob-based file discovery, ID-suffix aware
**Description:** Replace `find_song_audio()`'s exact-name-only matching with glob-based `song*.{ogg,opus,mp3,wav}` matching (per the spec's `find_reference_audio()` design), so ID-suffixed library folders (`song_1877.ogg`) are found. Extract a `find_song_ini()` helper (glob `*.ini`, preferring literal `song.ini` when multiple exist — matches `update_ini_with_offset`'s existing preference logic at line 549) so ini-lookup logic isn't duplicated. `find_video_file()` already correctly checks only literal `video.<ext>` candidates (confirmed it won't match cruft like `video.mp4.mkv.bak`) — add a regression test to lock that in rather than changing its logic.
**Acceptance criteria:**
- Finds `song.ogg` in a plain-convention fixture AND `song_1877.ogg` in an ID-suffixed fixture; returns `None` (never raises) for a fixture with no `song*` audio file.
- Never matches stem files (`guitar.ogg`, `drums_1.ogg`, `crowd_360.ogg`) in either fixture.
- `find_song_ini()` matches `update_ini_with_offset`'s current `song.ini`-preferred-else-first-match behavior for both naming conventions.
**Verification:**
```
pytest tests/test_offset_file_discovery.py -v
```
Manual spot-check: call the functions directly against 2-3 real folders in `M:\_Organized\Songs` (one plain, one ID-suffixed) to confirm songs that previously fell through to "no usable full-mix audio" now resolve.
**Dependencies:** None (parallel with Task 2).
**Files touched:** `clonehero_video_offset.py`, new `tests/test_offset_file_discovery.py`.
**Size:** S.

### Task 4: Byte-preserving, atomic song.ini patch scoped to video_start_time only
**Description:** Replace `update_ini_with_offset()` (currently interchanging `video_start_time`/`offset`/`song_offset`/`video_offset`) with a `patch_song_ini()` that **only ever touches `video_start_time`** (case-insensitive match), preserves every other line verbatim including the existing line-ending convention (CRLF vs LF — `song.ini` files were observed with Windows-style content; converting them to LF would be a real, if minor, corruption), handles both present-key (update in place) and missing-key (insert under `[song]`, matching Clone Hero's existing boilerplate which nearly always has the key present at `0` already) cases, and writes atomically via `tempfile.mkstemp(dir=song_folder)` + `os.replace()`.
**Acceptance criteria:**
- Unit tests feed real-shaped `song.ini` content (mixed casing, existing `video_start_time = 0`, missing the key, a song.ini that also happens to contain a chart `offset =` line before `video_start_time` — must NOT touch that line, CRLF and LF fixtures) and assert every other line is byte-identical in the output.
- A write failure mid-patch (mock `os.replace` to raise) leaves the original `song.ini` completely untouched.
- `apply_audio_offset()`'s call site is updated to use `patch_song_ini()`.
**Verification:**
```
pytest tests/test_song_ini_patch.py -v
```
**Dependencies:** Task 3 (shares the file-discovery layer).
**Files touched:** `CH-VideoScript.py`, new `tests/test_song_ini_patch.py` (supersedes the existing shallow ini-patch test in `tests/test_spreadsheet_lookup.py` — migrate that coverage in, then remove the old duplicate).
**Size:** M.

### ✅ Checkpoint 2 (after Tasks 3–4)
- `pytest tests/ -v` green.
- Manual: run `patch_song_ini()` against a copied real `song.ini` (both a plain-named and an ID-suffixed sample), diff before/after, confirm only the `video_start_time` line changed.

### Task 5: Swap correlation backend to audio-offset-finder
**Description:** Add `audio-offset-finder` and `numpy` to `pip-install.txt`. Replace `compute_offset()`'s librosa onset-strength + DTW implementation with a call to `audio-offset-finder`'s `find_offset_between_files()`, returning `(offset_ms, confidence)` where confidence is its reported "standard score." Remove now-dead DTW-specific constants (`WINDOW_S`, `MAX_TRUSTED_OFFSET_MS`, `MIN_CONFIDENCE_RATIO`) and the `librosa` import/dependency once nothing else in the codebase uses it (confirm via grep before removing from `pip-install.txt`). Map the new tool's confidence score to the existing `"ok"/"low_confidence"/"error"` status shape so `apply_audio_offset()`'s calling code doesn't need to change its branching, only the threshold value (0.5 on the new tool's scale, per the approved spec).
**Acceptance criteria:**
- `compute_offset(song_path, vid_audio)` returns the same `{"offset_ms", "confidence_ratio", "status"}` shape as before, sourced from `audio-offset-finder` instead of DTW.
- `librosa` is fully removed from imports and `pip-install.txt` if grep confirms no other usage.
- `pip install -r pip-install.txt` succeeds on a clean venv (flag immediately if `audio-offset-finder` fails to install on Windows — this is the plan's biggest technical risk; see Risks).
**Verification:**
```
pip install -r pip-install.txt
python -c "from clonehero_video_offset import compute_offset"
```
**Dependencies:** Task 4.
**Files touched:** `clonehero_video_offset.py`, `pip-install.txt`.
**Size:** M.

### Task 6: Sign-convention verification test — GATE, do not skip
**Description:** Build a synthetic audio fixture (short generated clip via numpy → WAV) plus a copy with a known, deliberately injected delay (`ffmpeg -itsoffset`). Run `compute_offset()` against the pair and assert the sign and magnitude of `offset_ms` matches the injected delay (both a positive and a negative case). This is the single highest-risk task: every `song.ini` write downstream depends on this being correct, and it has never been verified for either the old or the new backend.
**Acceptance criteria:**
- Test generates its own fixture at test time (nothing binary checked into git) and cleans up temp files.
- Asserts `compute_offset()`'s sign/magnitude for both a +250ms and a -250ms injected delay, within a small tolerance (e.g. ±20ms).
- If the sign is inverted, the fix is a one-line negation with a comment explaining why — not silently absorbed.
**Verification:**
```
ffmpeg -version   # confirm present first
pytest tests/test_compute_offset_sign.py -v -s
```
**Dependencies:** Task 5.
**Files touched:** new `tests/test_compute_offset_sign.py`.
**Size:** M.

### ✅ Checkpoint 3 (after Tasks 5–6) — hard gate
- `pytest tests/ -v` fully green, **including the sign test**.
- Do not proceed to Task 7+ if the sign test is failing or skipped — every subsequent write-path task builds on this.

### Task 7: VFR detection and CFR re-encode
**Description:** Add `probe_frame_rate(video_path)` (parses `ffprobe -show_entries stream=r_frame_rate,avg_frame_rate` JSON; VFR is where the two values disagree) and `reencode_to_cfr(video_path)` (ffmpeg re-encode to constant frame rate, overwriting the original file in place via an atomic write — extend Task 4's atomic-write helper to handle binary content, or add a parallel `atomic_replace_file()`). Run this before every `extract_audio`/`compute_offset` call in `apply_audio_offset()`. Log the outcome either way.
**Acceptance criteria:**
- `probe_frame_rate()`'s JSON-parsing logic is unit-tested against canned `ffprobe` output strings (VFR case, CFR case) — no real ffmpeg invocation needed for this part.
- Re-encode overwrites in place with no backup file left behind (confirmed decision), logged either way.
- `reencode_to_cfr()` itself is validated manually (mocking ffmpeg has low value) via a real VFR clip if one can be identified in the library, or via `--dry-run` output once Task 11 lands.
**Verification:**
```
pytest tests/test_vfr_probe_parsing.py -v
ffprobe -version
```
**Dependencies:** Task 6.
**Files touched:** `clonehero_video_offset.py`, new `tests/test_vfr_probe_parsing.py`.
**Size:** M.

### Task 8: video_meta.json offset fields + resumability
**Description:** Extend the existing per-folder `video_meta.json` (via `save_video_metadata`/`load_existing_video_confidence`, or new sibling functions) with `offset_ms`, `offset_confidence`, `offset_status` (`"written"`, `"low_confidence"`, `"vfr_exceeds_window"`, `"no_reference_audio"`, `"error"`), and `updated_at`. Gate `apply_audio_offset()` to skip folders whose `offset_status` is already settled on rerun — this is what makes a 5,131-song run interruptible.
**Acceptance criteria:**
- A folder with `offset_status: "written"` is skipped on a second run (verified via a call-count assertion on a mocked `compute_offset`).
- A folder with `offset_status: "error"` or no offset fields is retried on the next run.
- Every computed offset, including low-confidence ones, is persisted with its confidence score — never silently dropped.
**Verification:**
```
pytest tests/test_offset_resumability.py -v
```
Manual: run against a handful of real folders twice, confirm the second run's output shows them skipped.
**Dependencies:** Task 4 (patch function), Task 7 (VFR status feeds into offset_status).
**Files touched:** `CH-VideoScript.py`, new `tests/test_offset_resumability.py`.
**Size:** M.

### Task 9: scores.bin research spike (timeboxed, best-effort)
**Description:** Spend up to ~2 hours investigating whether Clone Hero's `scores.bin` can be parsed to determine "has this song been played to completion" (a proxy for "sync already manually confirmed"). Already known going in: the file at `AppData\LocalLow\srylain Inc_\Clone Hero\scores.bin` is only 358 bytes and last modified 2022-06-08 — likely stale relative to the real, current library, and it's an undocumented custom binary format (not JSON/protobuf-obviously-labeled). Check for prior community reverse-engineering (search for "Clone Hero scores.bin format") before attempting to reverse-engineer it from scratch.
**Acceptance criteria:**
- A clear written outcome: either (a) a minimal parser exists that can extract per-song play status, with the format documented, or (b) a documented decision to skip this and show "unknown" in the report, with the reason recorded.
- Whichever outcome, `SPEC.md`/plan is updated to reflect it before Task 10 starts — Task 10 must not block on this succeeding.
**Verification:** Manual — this is a spike, not a feature; its "test" is the written outcome document.
**Dependencies:** None (can run any time before Task 10; placed here since it feeds Task 10's column set).
**Files touched:** none, or a small `scores_bin_parser.py` if outcome (a).
**Size:** S (timeboxed explicitly — do not let this expand into a larger reverse-engineering project without checking back in first).

### ✅ Checkpoint 4 (after Tasks 7–9)
- `pytest tests/ -v` green.
- Confirm `ffmpeg -version`/`ffprobe -version` resolve.
- Task 9's spike outcome is documented and Task 10's scope is confirmed accordingly (with or without the CH-score column).

### Task 10: Library status report generator
**Description:** A new function/script (`generate_library_report()`, callable standalone or as a flag on the main script) that scans every song folder under `HOME_FOLDER` and emits a single reviewable file (CSV, since the user wants to review/edit song-file status at a glance — matches the spreadsheet-review pattern the existing `download_progress`-style review UX already uses elsewhere in the script) with one row per song: folder name, has-video (bool) + video confidence, has-offset (bool) + offset confidence/status, CH-score status (from Task 9's outcome — `unknown` if the spike didn't pan out), and a derived `needs_review` flag (e.g. true when offset confidence is low, video confidence is low, or status is `error`/`exceeds_window`). This is a read-only reporting pass over the `video_meta.json` files already being written by Tasks 5-8 — it does not introduce a second write-path state store.
**Acceptance criteria:**
- Running the report against a folder of synthetic fixtures (mixed video-meta states: fully confirmed, low-confidence offset, missing video, missing offset) produces one correct row per folder with accurate `needs_review` flagging.
- Report generation is read-only — confirmed it makes no writes to any `song.ini`, `video_meta.json`, or video file.
- Report includes enough identifying info (folder name, artist/title if parseable) that the user can act on a flagged row without re-deriving it.
**Verification:**
```
pytest tests/test_library_report.py -v
```
Manual: run against a real subset of `M:\_Organized\Songs`, open the resulting CSV, spot-check a few rows against the folders' actual `video_meta.json`/`song.ini` contents.
**Dependencies:** Task 8 (needs the offset fields to report on), Task 9 (needs the spike's outcome to know whether the CH-score column is populated or `unknown`).
**Files touched:** `CH-VideoScript.py` (or a new `library_report.py` if it grows large enough to warrant its own file — decide at implementation time based on actual size), new `tests/test_library_report.py`.
**Size:** M.

### Task 11: --dry-run wired end-to-end
**Description:** Add a `--dry-run` argparse flag (the script already uses `argparse` for `--threshold`/`--sample-size`/`--interactive`/`--skip-library-scan`, so this follows an established pattern). When set, `apply_audio_offset()` still runs VFR detection, extraction, and `compute_offset()`, and still logs the result — but skips the `song.ini` write, the video re-encode overwrite, and the `video_meta.json` persistence write.
**Acceptance criteria:**
- Running with `--dry-run` against a `tmp_path` fixture leaves `song.ini`, the video file, and `video_meta.json` byte-identical before/after, while still logging computed offset/confidence.
- Running without `--dry-run` on the same fixture does write all three.
**Verification:**
```
pytest tests/test_dry_run.py -v
python CH-VideoScript.py --dry-run   # against a small real subset if convenient
```
**Dependencies:** Task 8.
**Files touched:** `CH-VideoScript.py`, new `tests/test_dry_run.py`.
**Size:** S.

### ✅ Checkpoint 5 (after Tasks 10–11)
- Full suite green: `pytest tests/ -v`.
- `python CH-VideoScript.py --dry-run` run against a real (small) subset, log inspected for plausible offset/confidence values, zero files touched confirmed via before/after hash/mtime.
- Library report generated against that same subset and manually inspected.

### Task 12: Real-library validation and in-game playtest
**Description:** Not a code task — the spec's required proof step. Run the full pipeline (search → download → offset, non-dry-run) against a small batch of real, previously-unprocessed songs. Load at least one in Clone Hero and confirm the video visually syncs.
**Acceptance criteria:**
- At least one song's `song.ini` shows a correct `video_start_time`, confirmed in-game (not just "a number changed").
- Any low-confidence/error/exceeds-window outcomes from this run are recorded as known limitations, not silently ignored.
**Verification:** Manual — run script, launch Clone Hero, play the song(s), confirm sync.
**Dependencies:** Task 11.
**Files touched:** none.
**Size:** S (wall-clock, not implementation time).

### Task 13: Docs update
**Description:** Update `README.md`'s procedure section to document the offset phase, `--dry-run`, and the library report generator. Reconcile `SPEC.md` fully against what actually shipped (should mostly already match after Task 1, re-check after Tasks 2-12's real implementation details). Confirm `pip-install.txt` lists exactly what's needed.
**Acceptance criteria:**
- README explains: offset detection runs automatically after download, needs ffmpeg/ffprobe on PATH, `--dry-run` previews without writing, and how to run/read the library status report.
- `SPEC.md` Success Criteria checklist items are all checked off or explicitly noted as deferred, with no contradictions against shipped code.
**Verification:** Manual review.
**Dependencies:** Task 12.
**Files touched:** `README.md`, `SPEC.md`.
**Size:** XS.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| `audio-offset-finder` may not install cleanly on Windows (historically flaky audio-processing C-extension deps) | High — blocks Task 5, the whole correlation swap | Try the install first thing in Task 5, before writing any code against it; if it fails, fall back to hardening the existing librosa/DTW code instead (the alternate path already scoped by the earlier planning pass) rather than losing the session to dependency debugging |
| Sign convention has never been verified for either backend — real `song.ini` files may already have wrong `video_start_time` values from the currently-live, unverified DTW code | Medium — silent data corruption already possibly in progress | Task 6 gates all further write-path work; after it lands, consider spot-checking a sample of already-written `video_start_time` values against a manual playtest |
| `update_ini_with_offset`'s multi-key interchange bug could have already clobbered a real chart `offset` key in some song | Medium, low-likelihood (requires a specific line ordering) | Task 4 fixes this going forward; a full-library audit for already-corrupted files is out of scope for this plan but worth a follow-up spike if playtesting surfaces any songs with broken note timing |
| `scores.bin` may not be parseable, or may be from a stale/wrong profile | Low — cosmetic feature only | Task 9 is explicitly timeboxed with a documented no-go fallback; Task 10 does not depend on Task 9 succeeding |
| 5,131 songs is a lot of ffmpeg subprocess calls — a full run could take hours | Medium — affects Task 12 validation turnaround | Task 12 only requires validating a *small batch*, not the full library; full-library runs are the user's to schedule after this plan ships |
| Two logging mechanisms remain split (`print()` in `CH-VideoScript.py`, `RotatingFileHandler` in `clonehero_video_offset.py`) | Low — debugging friction only | Out of scope for this plan; flagged as a follow-up, not blocking |

## Verification (end-to-end)

1. `pytest tests/ -v` — all new and existing tests green, including the Task 6 sign-gate test.
2. `pip install -r pip-install.txt` on a clean venv succeeds.
3. `python CH-VideoScript.py --dry-run` against a small real subset of `M:\_Organized\Songs` — inspect log output for plausible offsets, confirm zero files modified.
4. `python CH-VideoScript.py` (no dry-run) against that same subset — confirm `song.ini`/`video_meta.json` updated correctly, rerun confirms resumability skips them.
5. Generate the library status report against that subset, manually inspect for correctness.
6. Load at least one processed song in Clone Hero, confirm the video is in sync.

## Open Questions (none blocking — for awareness only)

- Whether to eventually widen the (now audio-offset-finder-determined) analysis scope/window if songs with long video intros come back low-confidence — decide after Task 12's real-library validation shows how common that is.
- Whether to unify the two logging mechanisms — flagged as a follow-up, not part of this plan.
