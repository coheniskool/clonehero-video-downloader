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
   - auto-download files whose best video match meets or exceeds the confidence threshold
   - queue low-confidence matches for later review after all folders have been scored
3. During review, you can choose to download the best low-confidence candidate, skip the song, pick a different result, or enter a custom YouTube URL.

TIP
- Use `--threshold` to override the default auto-download cutoff.
- The script is interactive by default and will prompt for the confidence threshold after sampling rated candidates.
- Use `--no-interactive` to skip the prompt and use the default threshold.
- Use `--sample-size` to control how many rated folders are shown before choosing the threshold.
