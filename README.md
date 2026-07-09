# clonehero-video-downloader
Short python script that allows you to download the the top YouTube music video for songs in your Clone Hero library.

Disclaimer
-this is my first github repository so please message me with any feedback on how I can improve upon my work or the way I uploaded my work! :)

REQUIREMENTS
- Must have youtube-dl downloaded (https://github.com/ytdl-org/youtube-dl/blob/master/README.md#readme)
- Requires Python and the `yt_dlp` package installed in the project virtualenv

PROCEDURE
1. Change the `homeFolder` value in `CH-VideoScript.py` to the directory containing your individual song folders.
   For example: `homeFolder = "clonehero-win64\Songs\Guitar Hero 3"`
2. Run the program. If the `homeFolder` exists, the script will:
   - load the spreadsheet lookup table
   - sample a small, statistically-derived subset of your song folders and rate those first to help you choose a confidence threshold
   - prompt you (interactive mode) with sample statistics and example matches so you can pick a threshold
   - rate every folder, immediately downloading any result that meets or exceeds the chosen threshold
   - queue low-confidence matches for a manual review after all folders have been rated
   - continue if YouTube search requests fail, logging a warning and reporting the number of search failures at the end
3. During review, you can choose to download the best low-confidence candidate, skip the song, pick a different result, or enter a custom YouTube URL.

TIP
- Use `--threshold` to override the default auto-download cutoff.
- The script is interactive by default and will prompt for the confidence threshold after sampling rated candidates.
- Use `--no-interactive` to skip the prompt and use the default threshold.
- Use `--sample-size` to control how many rated folders are shown before choosing the threshold.

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
