# clonehero-video-downloader
Short python script that allows you to download the the top YouTube music video for songs in your Clone Hero library.

Disclaimer
-this is my first github repository so please message me with any feedback on how I can improve upon my work or the way I uploaded my work! :)

REQUIREMENTS
- Must have youtube-dl downloaded (https://github.com/ytdl-org/youtube-dl/blob/master/README.md#readme)
- Requires Python and the packages in `pip-install.txt` installed in the project virtualenv (`pip install -r pip-install.txt`)
- `ffmpeg`/`ffprobe` must be installed and on PATH -- used both for downloading (merging video/audio streams) and for offset detection (audio extraction, VFR detection/re-encode)
- numpy must land in the `>=2,<=2.4` window if you're installing manually: numpy 1.26.x breaks scipy's C extensions on newer Python, and numpy 2.5+ breaks numba (a dependency of `audio-offset-finder`, used for video offset detection). `pip-install.txt` already pins this correctly.

COOKIES
- By default the script pulls your YouTube session cookies from Chrome (`COOKIES_FROM_BROWSER = ("chrome",)` in `CH-VideoScript.py`) to reduce bot-detection false positives during downloads. This requires Chrome to be **fully closed** (not just the window -- check Task Manager for lingering `chrome.exe` processes) while the script runs, since Chrome locks its cookie database while open; otherwise every download fails with `Could not copy Chrome cookie database` (see https://github.com/yt-dlp/yt-dlp/issues/7271).
- If you don't want to keep Chrome closed during a run, export your cookies to a static file instead (e.g. with the "Get cookies.txt LOCALLY" browser extension) and set `COOKIES_FILE = "cookies.txt"` (or a full path) at the top of `CH-VideoScript.py`. `COOKIES_FILE` takes priority over `COOKIES_FROM_BROWSER` when set, and reading a static file has no locking issue.
- Note: only the download step uses cookies. The initial YouTube search step does not pass cookies at all, so a bot-detection block during *search* isn't fixed by either of the above.

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
