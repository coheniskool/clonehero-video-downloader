# clonehero-video-downloader
Short python script that allows you to download the the top YouTube music video for songs in your Clone Hero library.

Disclaimer
-this is my first github repository so please message me with any feedback on how I can improve upon my work or the way I uploaded my work! :)

FEATURES AT A GLANCE
- All of these are separate, standalone modes -- running one does **not** run the others. Each is documented in full further down; this table is just so you don't have to read the whole file to know what exists.

| What it does | Command |
|---|---|
| Download a background video for every song, auto-detect sync offset | `python CH-VideoScript.py` (default mode -- also runs a startup video-naming repair scan unless `--skip-library-scan`) |
| Fix ID-suffixed `song.ini`/`notes.chart`/`notes.mid`/audio-stem/album-art filenames | `python CH-VideoScript.py --scan-chart-names` |
| Fill blank `song.ini` metadata (year/genre/charter/album) from Chorus Encore | `python CH-VideoScript.py --enrich-metadata` |
| Find and relocate duplicate charts of the same song | `python dedupe_report.py --library-path <path>` (separate script, not a flag) |
| Library-wide video/offset coverage report (CSV) | `generate_library_report(homeFolder)` from a Python shell (not yet wired to a CLI flag) |

- Every mode that writes anything supports `--dry-run` to preview without touching a file (`dedupe_report.py` has its own `--dry-run`, same behavior).
- Full flag reference (all of `CH-VideoScript.py`'s flags together): see **ALL COMMAND-LINE FLAGS** near the end of this file.

REQUIREMENTS
- Must have youtube-dl downloaded (https://github.com/ytdl-org/youtube-dl/blob/master/README.md#readme)
- Requires Python and the packages in `pip-install.txt` installed in the project virtualenv (`pip install -r pip-install.txt`)
- `ffmpeg`/`ffprobe` must be installed and on PATH -- used both for downloading (merging video/audio streams) and for offset detection (audio extraction, VFR detection/re-encode)
- numpy must land in the `>=2,<=2.4` window if you're installing manually: numpy 1.26.x breaks scipy's C extensions on newer Python, and numpy 2.5+ breaks numba (a dependency of `audio-offset-finder`, used for video offset detection). `pip-install.txt` already pins this correctly.
- `requests` -- used by `chorus_client.py` (Chorus Encore metadata lookups, shared by `--enrich-metadata` and `dedupe_report.py`)
- `pyacoustid` (Python package) **and** `fpcalc` (a separate binary, must be on PATH) -- used only by `dedupe_report.py`'s duplicate detection. Get `fpcalc` from the official [AcoustID/Chromaprint release](https://acoustid.org/chromaprint), not an arbitrary download -- same trust bar as `ffmpeg`. Without it, `dedupe_report.py` still runs and reports candidate groups, but can never confirm or move anything (see **Duplicate Detection** below).

COOKIES
- By default the script pulls your YouTube session cookies from Chrome (`COOKIES_FROM_BROWSER = ("chrome",)` in `CH-VideoScript.py`) to reduce bot-detection false positives during downloads. This requires Chrome to be **fully closed** (not just the window -- check Task Manager for lingering `chrome.exe` processes) while the script runs, since Chrome locks its cookie database while open; otherwise every download fails with `Could not copy Chrome cookie database` (see https://github.com/yt-dlp/yt-dlp/issues/7271).
- If you don't want to keep Chrome closed during a run, export your cookies to a static file instead (e.g. with the "Get cookies.txt LOCALLY" browser extension) and set `COOKIES_FILE = "cookies.txt"` (or a full path) at the top of `CH-VideoScript.py`. `COOKIES_FILE` takes priority over `COOKIES_FROM_BROWSER` when set, and reading a static file has no locking issue.
- Note: only the download step uses cookies. The initial YouTube search step does not pass cookies at all, so a bot-detection block during *search* isn't fixed by either of the above.

VIDEO FORMAT
- Downloads prefer MP4 first, confirmed working by real playtesting. An earlier attempt to prefer WebM was reverted after Clone Hero's own log showed `Error: Unsupported video codec 'VP9'` and the video never rendering at all -- YouTube's WebM streams are almost always VP9 (or AV1) now, and this Clone Hero build only decodes VP8 WebM. If a video has no MP4 stream at all, the WebM fallback is explicitly constrained to `vcodec=vp8` so it can never silently grab an incompatible stream.
- The startup library scan (`scan_and_fix_video_library()`, runs unless `--skip-library-scan`) now also checks the codec of every *existing* `video.webm` it finds (both already-canonically-named ones and ones it's about to rename into place) and **deletes** it if the codec isn't VP8, logging it as "removed for an unsupported codec." That song then has no video file, so it's picked up for a fresh (MP4) download on the same run.
- A full library scan run during development found **455 pre-existing WebM videos** (416 AV1, 39 VP9) that predated this fix entirely and were silently unplayable in Clone Hero -- none of that was caused by this tool's downloads; it looks like whatever process originally built the library grabbed AV1/VP9 streams without codec awareness. If you're seeing a lot of `[unsupported codec]` removals on your first run after updating, that's expected cleanup, not a new problem.

PROCEDURE
1. Run the program. It will prompt for your Clone Hero songs library path at startup:
   `Enter your Clone Hero songs library path (or press Enter for M:\_Organized\Songs): `
   Type the path to the directory containing your individual song folders and press Enter, or just press Enter to accept the default shown (edit `DEFAULT_HOME_FOLDER` in `CH-VideoScript.py` if you always use a different library and don't want to type it every run). Pass `--library-path <path>` to skip the prompt entirely (also used automatically with `--no-interactive`).
2. If the path exists, the script will:
   - load the spreadsheet lookup table
   - sample a small, statistically-derived subset of your song folders and rate those first to help you choose a confidence threshold
   - prompt you (interactive mode) with sample statistics and example matches so you can pick a threshold
   - rate every folder, immediately downloading any result that meets or exceeds the chosen threshold
   - queue low-confidence matches for a manual review after all folders have been rated
   - continue if YouTube search requests fail, logging a warning and reporting the number of search failures at the end
3. During review, you can choose to download the best low-confidence candidate, skip the song, pick a different result, or enter a custom YouTube URL.
4. After each video downloads, the script automatically detects the audio/video sync offset and writes it to that song's `song.ini` as `video_start_time` -- see **Video Offset Detection** below.

TIP
- Use `--library-path <path>` to skip the startup path prompt (useful for scripting/automation).
- Use `--threshold` to override the default auto-download cutoff.
- The script is interactive by default and will prompt for the confidence threshold after sampling rated candidates.
- Use `--no-interactive` to skip the prompt and use the default threshold.
- Use `--sample-size` to control how many rated folders are shown before choosing the threshold.
- While sampling is running, you can type a confidence level (0-100) and press Enter at any time to stop sampling early and use that value as the threshold immediately, instead of waiting for the whole sample to finish. Windows only.
- Use `--dry-run` to preview computed video offsets (logged to the console) without writing to any `song.ini`, re-encoding any video, or updating `video_meta.json`. Search and download still happen normally -- only the offset-writing step is previewed.
- Use `--skip-library-scan` to skip the startup scan that repairs mis-named/mis-muxed video files already in your library.

VIDEO OFFSET DETECTION
- After a video downloads (or if one already exists), the script extracts the video's audio track and cross-correlates it against the song's own backing-track audio (`audio-offset-finder`, MFCC-based) to compute the millisecond offset needed to sync the video to the chart. That value is written to `song.ini` as `video_start_time`.
- If a spreadsheet row has its own `Offset` value, that's used instead of computing one -- spreadsheet offsets are treated as pre-vetted and take priority. Like computed offsets, a spreadsheet-sourced offset is recorded in `video_meta.json` once applied and is skipped on later runs -- it does not get rewritten (or re-read from the spreadsheet) every time you run the script.
- Variable Frame Rate (VFR) source video is detected automatically and re-encoded to Constant Frame Rate (CFR) in place before offset computation, since VFR causes progressive desync that a single offset value can't fix.
- Every attempt's outcome (including low-confidence or failed ones) is recorded in that song's `video_meta.json`, and a song whose offset already reached a settled result is skipped on the next run -- so re-running the script over your whole library doesn't recompute everything from scratch.
- The confidence score is a z-score-like "standard score" from `audio-offset-finder`, not a percentage. Real-world scores on actual downloaded videos in early testing came in noticeably lower (around 2-3) than a clean synthetic test signal (around 8-9) -- if a lot of songs are landing in `low_confidence`, that threshold may need recalibrating; check `MIN_STANDARD_SCORE` in `clonehero_video_offset.py`.
- **Always spot-check a computed offset by loading the song in Clone Hero.** A written `video_start_time` is not guaranteed correct until confirmed in-game -- external validation isn't sufficient (Clone Hero's own decoder can behave differently than a general media player).

LIBRARY STATUS REPORT
- Run `generate_library_report(homeFolder)` (from a Python shell, or wire it to a future CLI flag) to scan every song folder and write `library_status_report.csv` into your library root.
- Each row shows: folder/artist/title, whether a video exists and its match confidence, whether an offset was set and its confidence/status/source (`computed` via audio correlation, or `spreadsheet`), a Clone Hero played-score status (currently always `unknown` -- see `SPEC.md`'s Open Questions for why), and a `needs_review` flag for anything missing or unconfirmed.
- This is read-only -- it never modifies `song.ini`, `video_meta.json`, or any video file, so it's safe to run at any time to check overall library coverage.

CHART FILE RENAME (`--scan-chart-names`)
- Some song folders end up with numeric-ID-suffixed chart files instead of the literal names Clone Hero requires -- `song_2400.ini` instead of `song.ini`, `notes_454.chart` instead of `notes.chart`. Clone Hero can't load these folders at all. The same bug also affects audio-stem filenames (`song_1877.ogg` instead of `song.ogg`) and album art (`album_827.png` instead of `album.png`).
- Run `python CH-VideoScript.py --scan-chart-names` (opt-in, standalone -- runs instead of the normal search/download flow) to scan the whole library. For each ID-suffixed file found, the script verifies the content actually matches the folder's stated song before renaming: `.chart` files via fuzzy-matching the embedded `Name`/`Artist` against `song.ini`; `.mid` files (no embedded metadata) via comparing the paired audio's real duration against `song.ini`'s `song_length`.
- If content is confirmed, the file is renamed. If it can't be confirmed -- or a stem/album-art role has more than one candidate file (ambiguous, can't be resolved automatically) -- the **whole folder** is relocated intact to a `_needs_review/` folder at your library root, never renamed under a guess.
- Use `--dry-run` to preview what would be renamed/relocated without touching any file.
- A folder that finishes fully verified is marked `confirmed_ok` in its `video_meta.json`, so a rerun skips it -- only new or previously-flagged folders are reprocessed.

METADATA ENRICHMENT (`--enrich-metadata`)
- Looks up each song on the [Chorus Encore](https://www.enchor.us/) chart database by artist+title and fills in **blank or missing** `song.ini` fields (`year`, `genre`, `charter`, `album`) from a confident match. It never overwrites a field that already has a value.
- Run `python CH-VideoScript.py --enrich-metadata` (opt-in, standalone). Combine with `--dry-run` to preview without writing anything.
- Album art is **not** supported by this feature -- confirmed that Chorus Encore's API doesn't track album art as queryable/returned data at all (only a hash of the art file, no URL or image data).

DUPLICATE DETECTION (`dedupe_report.py`)
- A separate script (not a flag on `CH-VideoScript.py`) that finds duplicate charts of the same song from different sources, scores each copy, and moves everything except the best-scoring "keeper" into a `_duplicates_review` folder at your library root for you to review and eventually delete by hand. **Nothing is ever deleted automatically.**
- Run `python dedupe_report.py --library-path <path>`. Combine with `--dry-run` to preview groups/scores without moving anything.
- Requires `fpcalc` (see REQUIREMENTS above) to actually confirm and act on duplicates -- fuzzy title/artist matching alone only produces *candidate* groups (e.g. it correctly won't group a studio track with a "(Live)" version of the same song, but it also can't tell two different recordings of the exact same title apart without audio fingerprinting). Without `fpcalc` installed, the script still runs and reports how many candidate groups it found, but confirms and moves nothing.
- The report also flags "borrow candidates" -- things a discarded copy has that the keeper lacks (a Pro Drums chart, a set difficulty, a background video) -- so you know if a manual merge might be worth doing before deleting that copy. This is report-only; the script never merges anything itself.
- Scoring favors instrument/chart completeness above all else (the actual playable content), with video presence, sync confidence, metadata completeness, and a Chorus quality signal as smaller factors.

WHICH TOOL DO I RUN, AND WHAT DO I DO ABOUT THE RESULT?
- **`_needs_review/`** (from `--scan-chart-names`): a folder whose chart/audio/album-art content couldn't be confidently verified. Open it, figure out what it actually is by hand, fix the naming yourself, and move it back into your library root.
- **`_duplicates_review/`** (from `dedupe_report.py`): folders that lost to a better-scoring copy of the same song. Read the report for the "borrow candidate" notes, then delete them yourself once you're satisfied nothing's worth keeping.
- **`--enrich-metadata`'s output**: no folder relocation at all -- it only ever edits `song.ini` fields in place, and only fills things in that were blank. Check the console log for which songs got fields filled, or which had no confident match.
- If you're not sure which tool produced a given folder/log line, check `_needs_review_manifest.jsonl` / `_duplicates_review_manifest.jsonl` at your library root -- both record every relocation with its reason.

**Confidence workflow (summary)**

- The script first scans your `homeFolder` and builds the list of song folders (no network requests).
- It computes a recommended sample size using Cochran's formula (95% CI by default) unless you pass `--sample-size`.
- It randomly rates only that sample using `yt_dlp` searches and prints descriptive statistics (mean, median, mode, std, range).
- You use those sample statistics and example results to pick an auto-download confidence threshold.
- After you choose the threshold, the script rates every folder; any match at-or-above the threshold is downloaded immediately.
- Any matches below the threshold are queued for manual review once automatic downloads finish.

**Confidence levels (what they mean)**
 90-100: Very high confidence (exact artist + title match, official)
 70-89:  High confidence (good match, may be official)
 50-69:  Medium confidence (partial match)
 0-49:   Low confidence (weak match, likely wrong video)

**Troubleshooting & notes**

- Network / YouTube errors: `yt_dlp` network or extraction failures are caught and logged per-search; the script increments a `search_failures` counter and continues. At the end you'll see how many searches failed.
- Ctrl+C / interrupts: Keyboard interrupts are preserved so you can stop the script with Ctrl+C.
- Spreadsheet parsing: The script expects spreadsheet rows to contain `Artist` and `Song` columns (case-insensitive). If a row is missing a `Song` value it is skipped.
- SequenceMatcher errors: There have been rare crashes reported in the Python `difflib.SequenceMatcher` call when input data is malformed. If you see a traceback referencing `difflib.py` and `find_longest_match`, please check your spreadsheet for empty or non-string cells in the `Song` column and open an issue with a short sample of the offending row. The script now guards common failure modes, but malformed CSV data can still surface edge-cases.

- Spreadsheet indexing timing: The script performs spreadsheet matching (indexing) after the sampling step and after you choose the confidence threshold. This ensures the sample statistics you use to pick a threshold are not biased by spreadsheet URL overrides. After you confirm a threshold, spreadsheet entries are applied as overrides (spreadsheet URLs receive high confidence and are prioritized for immediate download).

**Example run snippet**

```
======================================================================
CONFIDENCE VERIFICATION SETTINGS
======================================================================
Videos will be rated 0-100 based on how well they match your search.
You can choose to verify videos below a certain confidence level.

Confidence levels:
   90-100: Very high confidence (exact artist + title match, official)
   70-89:  High confidence (good match, may be official)
   50-69:  Medium confidence (partial match)
   0-49:   Low confidence (weak match, likely wrong video)

Preparing confidence ratings for all song folders...
Loaded 570 spreadsheet rows for matching.
Found spreadsheet entry for: .38 Special (WaveGroup) - Hold On Loosely
   Offset: -2700
... (sampleed matches, then statistics and prompt) ...
Traceback (most recent call last):
   ...
   File "CH-VideoScript.py", line 374, in find_sheet_match
      score += int(SequenceMatcher(None, search_title_norm, title_norm).ratio() * 30)
   File "C:\Python314\Lib\difflib.py", line 379, in find_longest_match
      for j in b2j.get(a[i], nothing):
```

If you see the `difflib` traceback above, inspect your spreadsheet CSV for malformed or empty `Song` cells and re-run.

ALL COMMAND-LINE FLAGS

`python CH-VideoScript.py [flags]`

| Flag | Effect |
|---|---|
| `--library-path <path>` | Path to your Clone Hero songs library folder. Skips the startup prompt when set. |
| `--threshold <int>` | Minimum confidence required to auto-download without confirmation. |
| `--interactive` / `--no-interactive` | Prompt for the confidence threshold (default), or skip the prompt and use the default threshold. Mutually exclusive. |
| `--sample-size <int>` | Max number of rated songs to sample before asking for a threshold; Cochran's 95% CI formula picks the size when this is 0 (default). |
| `--skip-library-scan` | Skip the startup scan that repairs mis-named/mis-muxed video files already in your library. |
| `--dry-run` | Preview without writing: applies to the normal offset-writing step, and to `--scan-chart-names`/`--enrich-metadata` when combined with either. |
| `--scan-chart-names` | Opt-in, standalone (see CHART FILE RENAME above) -- runs instead of the normal search/download flow. |
| `--enrich-metadata` | Opt-in, standalone (see METADATA ENRICHMENT above) -- runs instead of the normal search/download flow. |

`python dedupe_report.py [flags]` (separate script)

| Flag | Effect |
|---|---|
| `--library-path <path>` | **Required.** Path to your Clone Hero songs library folder. |
| `--dry-run` | Compute groups/scores/borrow-candidate flags and log them without moving any folder. |

`--scan-chart-names` and `--enrich-metadata` are mutually exclusive with each other and with the normal download flow in practice -- whichever is passed first in the code's check order (`--scan-chart-names`, then `--enrich-metadata`) runs and the script exits; pass only one at a time.
