# Spec: Video Offset Calculator for clonehero-video-downloader

## Objective

`CH-VideoScript.py` downloads a background video for every song in a Clone Hero library and drops it into the song's folder as `video.mp4`/`video.webm`. Historically it didn't sync that video to the chart — the user had to nudge `video_start_time` by hand in Clone Hero's pause menu for every single song.

This feature adds an offset-detection phase to the script: after a video downloads, automatically compute the millisecond offset needed to align it with the song's audio and write that value into the song's `song.ini` as `video_start_time`. This closes the loop from "video downloaded" to "video plays in sync," with no manual per-song tuning. It also adds a library-wide status report so the ~5,131-song library's video/offset coverage can be reviewed at a glance.

**Method**: extract the downloaded video's own audio track, cross-correlate it against the song's existing chart audio using audio-domain correlation (far more precise than any manual tap-test or frame-based method), and convert the resulting lag into the `video_start_time` value. Backend: [`audio-offset-finder`](https://github.com/bbc/audio-offset-finder) (MFCC-based cross-correlation), per the `clone-hero-video-offset-detection` research sweep.

**Reconciliation note (2026-07-11):** while this spec was originally being written, an independent branch (`coheniskool-effective-giggle`) was fast-forward merged into `master`, growing `CH-VideoScript.py` from ~200 to 1,208 lines and adding a working-but-buggy offset-detection feature using **librosa + DTW** in a new `clonehero_video_offset.py` module, plus a spreadsheet-lookup feature, confidence-threshold review flow, and per-folder `video_meta.json` persistence (replacing what this spec originally assumed would be a `download_progress.csv`). This spec has been updated to describe the real, current codebase and the decisions made during `/plan` to reconcile against it — see `tasks/plan.md` for the full task-by-task breakdown and the bugs found in the merged code.

**User**: solo hobbyist (the script's existing/only user), run locally and interactively on Windows, same trust model as the existing script — no multi-user, no server, no auth.

**Success looks like**: run `python CH-VideoScript.py`, and by the time it finishes, every downloaded video's `song.ini` has a `video_start_time` that syncs correctly in-game, without the user touching the pause menu — and a single report file exists that shows, per song, whether video/offset/play-history data is present and which songs need manual review.

## Tech Stack

- Python 3.x (matches existing script; no version pin currently enforced)
- **Correlation backend**: [`audio-offset-finder`](https://github.com/bbc/audio-offset-finder) (pip) — MFCC-based cross-correlation, ffmpeg-backed, ~10ms typical accuracy, reports a confidence "standard score". Confirmed during `/plan`: this replaces the `librosa`+DTW implementation that was merged in independently — not a hardening of that code, a swap.
- `numpy` (dependency of `audio-offset-finder`)
- `librosa` and `tqdm` are being **removed** as dependencies once the swap to `audio-offset-finder` lands and no other code in the repo depends on them (confirm via grep before removing from `pip-install.txt`)
- **External binary**: `ffmpeg`/`ffprobe` on PATH — already an implicit requirement (yt-dlp uses it to merge video+audio streams); this feature adds direct calls to it for (a) VFR detection via `ffprobe`, (b) VFR→CFR re-encoding, and (c) audio-track extraction
- No new framework, no database — persistence is per-folder `video_meta.json` (already the existing pattern for video-match confidence), extended with offset fields; the library-status report is a read-only reporting pass over those files, not a second write-path store

## Commands

```
Setup:  pip install -r pip-install.txt        (audio-offset-finder, numpy; librosa/tqdm removed once unused)
        ffmpeg must be installed and on PATH   (not pip-installable; verify with `ffmpeg -version`)
Run:    python CH-VideoScript.py               (search -> download -> offset, all in one pass)
Dry run: python CH-VideoScript.py --dry-run    (computes and logs offsets, writes nothing to song.ini, video files, or video_meta.json)
Report: python CH-VideoScript.py --report      (or a standalone report entry point -- decide at Task 10 implementation time; generates the library status CSV)
Test:   pytest tests/ -v
```

## Project Structure

The offset-detection logic already lives in its own module (`clonehero_video_offset.py`), imported by `CH-VideoScript.py` behind an `OFFSET_SUPPORT` try/except guard so the search/download flow still works if the offset module or its dependencies are unavailable. This structure is kept as-is (not flattened into one file — that decision predates the discovery that a real module split already exists in the merged code).

```
CH-VideoScript.py          -> Main script: folder scanning, YouTube search, spreadsheet
                               lookup, confidence review, download, and orchestration of
                               the offset phase via apply_audio_offset(). Also owns
                               update_ini_with_offset() (being replaced by patch_song_ini()),
                               save_video_metadata()/load_existing_video_confidence()
                               (video_meta.json read/write, being extended with offset fields).
clonehero_video_offset.py  -> Offset-detection module: find_song_audio(), find_video_file(),
                               extract_audio(), compute_offset() (DTW being swapped for
                               audio-offset-finder), probe_frame_rate()/reencode_to_cfr()
                               (new, VFR handling). The standalone batch_process()/CLI entry
                               point is being removed (dead code, race risk).
pip-install.txt             -> audio-offset-finder, numpy (librosa/tqdm removed once unused)
tests/
  test_spreadsheet_lookup.py     -> Existing coverage (has a shallow ini-patch test being
                                     superseded by test_song_ini_patch.py)
  test_offset_file_discovery.py  -> New: find_song_audio/find_song_ini/find_video_file,
                                     both real naming conventions
  test_song_ini_patch.py         -> New: byte-preserving atomic patch_song_ini()
  test_compute_offset_sign.py    -> New: sign-convention gate, synthetic fixture only
  test_vfr_probe_parsing.py      -> New: probe_frame_rate() JSON parsing
  test_offset_resumability.py    -> New: video_meta.json offset-status skip logic
  test_dry_run.py                -> New: --dry-run touches zero files
  test_library_report.py         -> New: report generator correctness
README.md                   -> To be updated (Task 13) to document the offset phase,
                               --dry-run, and the library report
```

## Code Style

Match the existing script exactly — same voice, same patterns:

```python
def compute_offset(song_path, vid_audio):
	#returns {"offset_ms", "confidence_ratio", "status"} using audio-offset-finder's MFCC
	#cross-correlation; status is "ok"/"low_confidence"/"error", mirroring the shape the
	#DTW implementation returned so apply_audio_offset()'s branching doesn't need to change
	offset_seconds, confidence = find_offset_between_files(str(song_path), str(vid_audio))
	offset_ms = round(offset_seconds * 1000)
	if confidence < MIN_CONFIDENCE:
		return {"offset_ms": offset_ms, "confidence_ratio": confidence, "status": "low_confidence"}
	return {"offset_ms": offset_ms, "confidence_ratio": confidence, "status": "ok"}


def find_song_audio(song_dir):
	#the full backing mix, not a stem -- filename is always "song*" regardless of numeric
	#suffix (confirmed against the real library: some folders use "song.ogg", others use
	#"song_1877.ogg" from a different chart source). Never matches guitar/drums/rhythm/
	#vocals/keys/crowd stems, which use their own prefixes.
	for ext in (".ogg", ".opus", ".mp3", ".wav"):
		matches = list(song_dir.glob("song*" + ext))
		if matches:
			return matches[0]
	return None


def find_song_ini(song_dir):
	#also inconsistently named across the library ("song.ini" vs "song_2400.ini") -- there is
	#always exactly one *.ini file per song folder regardless of chart source, so match on that,
	#preferring the literal "song.ini" name when more than one .ini exists
	ini_files = sorted(song_dir.glob("*.ini"))
	if not ini_files:
		return None
	return next((p for p in ini_files if p.name.lower() == "song.ini"), ini_files[0])


def find_video_file(song_dir):
	#always literally "video.<ext>" -- this is the outtmpl the download phase already writes,
	#so unlike song.ini/song audio this name is never suffixed or renamed. Must not match
	#leftover cruft like "video.mp4.mkv.bak" from old bugs -- exact-name check handles that.
	for name in ("video.mp4", "video.avi", "video.webm", "video.ogv"):
		candidate = song_dir / name
		if candidate.exists():
			return candidate
	return None
```

- Tabs for indentation (matches existing file)
- `.format()`-style string formatting where the surrounding code already uses it; f-strings are also present in the merged code and are fine to use in new/touched functions there — match whichever convention the immediate function already uses rather than converting wholesale
- One function per discrete step, no classes (matches existing file's procedural style)
- Reuse existing logging: `print()` in `CH-VideoScript.py`, the `RotatingFileHandler`-based `logging` calls in `clonehero_video_offset.py` — unifying these is an explicitly out-of-scope follow-up, not part of this feature
- Atomic writes (`tempfile.mkstemp` + `os.replace`) for `song.ini` and any re-encoded video file — this is new discipline being introduced (the current `update_ini_with_offset()` does a plain `write_text()`, not atomic)
- Comments explain *why*, not *what*

## Testing Strategy

The existing script has one test file, `tests/test_spreadsheet_lookup.py`, confirmed by direct inspection. `song.ini` mutation is the one operation here with real corruption risk (a bad write breaks the song in Clone Hero), so it gets a real safety net; VFR/ffmpeg-heavy paths rely on `--dry-run` + manual verification instead of mocking.

- **Unit-tested**: `find_song_audio()`/`find_song_ini()`/`find_video_file()` against synthetic folder fixtures covering both real naming patterns (plain and ID-suffixed), plus a no-reference-audio fixture (must return `None`, never raise) — `tests/test_offset_file_discovery.py`. The `song.ini` patch function (`patch_song_ini()`) — real-shaped `.ini` content including a stray chart `offset =` line that must NOT be touched, CRLF/LF preservation, missing-key insertion — `tests/test_song_ini_patch.py`. `probe_frame_rate()`'s JSON-parsing logic against canned `ffprobe` output (VFR vs CFR cases, no real ffmpeg call needed) — `tests/test_vfr_probe_parsing.py`. Resumability (`video_meta.json` offset-status skip logic) — `tests/test_offset_resumability.py`. `--dry-run` file-untouched guarantee — `tests/test_dry_run.py`. Library report correctness against synthetic `video_meta.json` fixtures — `tests/test_library_report.py`.
- **Sign-convention verification uses dedicated test files, not the real library** (`tests/test_compute_offset_sign.py`): build a synthetic fixture — a short reference clip plus a copy with a *known, deliberately injected* delay (`ffmpeg -itsoffset`) — run `compute_offset()` against the pair, confirm sign/magnitude match. This is a hard gate (plan Checkpoint 3): no further write-path task proceeds until it passes, because the sign has never been verified for either the old DTW code or the new backend.
- **Not unit-tested** (mocking ffmpeg/network has low value for a personal script): `reencode_to_cfr()` itself, and correlation behavior against real videos. Validated by `--dry-run` output inspection plus a required **manual in-game playtest** — a computed offset is not trustworthy until confirmed inside Clone Hero itself.
- No CI — local script, run on-demand.

## Boundaries

- **Always**:
  - Preserve every existing `song.ini` line/comment/key verbatim except `video_start_time` — never reformat, reorder, or touch a different key (the merged code's `update_ini_with_offset()` currently violates this by interchanging `video_start_time`/`offset`/`song_offset`/`video_offset` — being fixed)
  - Use atomic writes (temp file + `os.replace`) for `song.ini` and any re-encoded video file
  - Run VFR detection (`ffprobe`) before computing an offset, and re-encode to CFR automatically if VFR is detected, overwriting the original video file in place (no backup kept), logging that this happened
  - Persist every computed offset and its confidence score to `video_meta.json`, even when confidence is low — never silently drop a result
  - Skip songs whose `offset_status` in `video_meta.json` is already settled on rerun
  - Support `--dry-run` so offsets can be reviewed before any file is touched
  - Keep the library-status report read-only — it reports on `video_meta.json`/`song.ini` state, it never writes to them

- **Ask first**:
  - Changing the default low-confidence threshold (`0.5` on `audio-offset-finder`'s standard-score scale — confirmed as the starting default)
  - Adding any dependency beyond `audio-offset-finder`/`numpy`
  - Expanding the `scores.bin` research spike (Task 9) beyond its ~2 hour timebox

- **Never**:
  - Never modify the `.chart`/`.mid` file or any note-timing-related key (`delay`, chart-internal `offset`/`song_offset`/`video_offset`) — scoped to `video_start_time` only
  - Never delete a song folder's chart, audio, or metadata files
  - Never write a computed offset to `song.ini` when `compute_offset()` fails outright — only skip on failure; low confidence still gets written + flagged
  - Never commit `video_meta.json`, the library report CSV, log files, or any song/video data to git — user data, not repo content

## Success Criteria

- [ ] Running `python CH-VideoScript.py` end-to-end (search → download → offset) leaves every newly-downloaded song's `song.ini` with a correct `video_start_time` value
- [ ] `video_meta.json` gains `offset_ms`, `offset_confidence`, `offset_status`, `updated_at` fields; the offset phase is resumable (settled songs skipped on rerun)
- [ ] VFR source video is detected and transparently re-encoded to CFR before offset computation, logged either way
- [ ] `tests/test_song_ini_patch.py` passes and proves the patch function never corrupts unrelated `song.ini` content, and never touches a non-`video_start_time` key
- [ ] `tests/test_compute_offset_sign.py` passes — sign convention empirically verified, not assumed
- [ ] `--dry-run` computes and logs offsets without writing to `song.ini`, any video file, or `video_meta.json`
- [ ] A library-status report can be generated showing, per song: video present/confidence, offset present/confidence/status, CH-score status (always `unknown` per the Task 9 spike's no-go decision), and a `needs_review` flag
- [ ] The dead `batch_process()`/CLI entry point in `clonehero_video_offset.py` is removed
- [ ] At least one song, manually playtested in Clone Hero after an automated offset write, plays in sync

## Open Questions

**Resolved during spec review (original /spec session):**
- ~~Which file is "the chart audio"~~ → glob-based `find_song_audio()` matching `song*.{ogg,opus,mp3,wav}`, handling both plain and numeric-ID-suffixed naming found in the real library.
- ~~Low-confidence threshold~~ → confirmed default of `0.5`.
- ~~CFR re-encode backup~~ → confirmed: overwrite the original video file in place, no backup.

**Resolved during /plan (after discovering the independent merge):**
- ~~Keep librosa/DTW or swap to audio-offset-finder~~ → swap, per the original spec's tech choice, not a hardening of the merged DTW code.
- ~~Central CSV vs per-folder video_meta.json~~ → keep `video_meta.json`, add the library-status report as a read-only aggregate view on top of it (not a second write-path store).
- ~~Sign convention~~ → resolved by verification method, not by guessing: `tests/test_compute_offset_sign.py` against a synthetic fixture with a known injected offset, required before any further write-path work (plan Checkpoint 3).
- ~~Dead `batch_process()`/CLI entry point~~ → remove it (race risk against the same files as the main flow, never called from `main()`).

**Resolved: Task 9 scores.bin spike — SKIP, use "unknown".** Within the ~2 hour timebox: a real community parser exists ([matthiasduyck/CloneHeroSaveGameEditor](https://github.com/matthiasduyck/CloneHeroSaveGameEditor), `ScoresData.cs`/`ScoreEntry.cs`), but even that project's own code has multiple unresolved `//todo unknown field` comments, and it splits entries on a literal byte-value-32 delimiter — fragile, since several real fields (raw percentages, star counts) can legitimately equal that byte value. More importantly, each entry only stores an opaque `SongIdentifier` hash, not a folder path; resolving it to an actual song folder requires *also* reverse-engineering `songcache.bin`, a second undocumented format the reference project hasn't solved either (confirmed via its own `TASKS_TODO.md`). On this machine, `scores.bin` itself is stale (358 bytes, last modified 2022-06-08) while `songcache.bin` was updated the day before this session — so even a working parser would surface almost no real data against the 5,131-song library. **Decision: no parser is built. The library-status report's CH-score column always shows `unknown`.**

**Still open:**
- Whether to eventually widen the correlation analysis window if songs with long video intros come back low-confidence — decide after real-library validation (Task 12) shows how common that is.
- Whether to unify the two logging mechanisms (`print()` vs `RotatingFileHandler`) — flagged as a follow-up, not part of this feature.
