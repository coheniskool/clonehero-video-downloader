#import youtube-dl
from __future__ import unicode_literals
import yt_dlp

import argparse
import csv
import io
import json
import math
import os
import random
import re
import statistics
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

try:
    import msvcrt
except ImportError:
    msvcrt = None

# Title cleaning patterns (adapted from Playlist Sentiment project)
# Strips noise like "(feat. X)", "- Remastered", "(Live)", etc.
_TRAILING_PAREN_NOISE_RE = re.compile(
    r"\s*[\(\[]\s*(?:"
    r"feat\.?|ft\.?|featuring|live|radio\s*edit|acoustic|explicit|clean|"
    r"single\s*version|album\s*version|remix|"
    r"remaster(?:ed)?(?:\s*\d{2,4})?"
    r")\b[^)\]]*[\)\]]\s*$",
    re.IGNORECASE,
)

_TRAILING_DASH_NOISE_RE = re.compile(
    r"\s*-\s*(?:"
    r"feat\.?|ft\.?|featuring|live|radio\s*edit|"
    r"single\s*version|album\s*version|"
    r"remaster(?:ed)?(?:\s*\d{2,4})?|\d{2,4}\s*remaster"
    r")\b.*$",
    re.IGNORECASE,
)

_PEDAL_NOISE_RE = re.compile(
    r"\s*[\(\[]\s*(?:\d+\s*x\s+)?(?:bass\s+)?pedal(?:\s*\d+\s*x)?(?:\s*(?:expert|hard|medium|easy|normal|plus|\+))?[^)\]]*[\)\]]\s*$",
    re.IGNORECASE,
)

_PEDAL_IN_TITLE_RE = re.compile(
    r"\b(?:\d+\s*x\s+)?(?:bass\s+)?pedal(?:\s*\d+\s*x)?(?:\s*(?:expert|hard|medium|easy|normal|plus|\+))?\b",
    re.IGNORECASE,
)

_DIFFICULTY_RESULT_RE = re.compile(
    r"\b(?:expert|hard|medium|easy|normal|beginner|advanced)(?:\+|\s+plus)?\b",
    re.IGNORECASE,
)

VIDEO_FILE_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".flv", ".mp3", ".m4a"}
VIDEO_METADATA_FILENAME = "video_meta.json"
search_failures = 0

#Default answer to the library-path prompt at startup (press Enter to accept it).
#Change this if you always point the script at the same library and don't want to
#type it every run; --library-path overrides both this and the prompt entirely.
DEFAULT_HOME_FOLDER = r"M:\_Organized\Songs"

#Browser to pull YouTube session cookies from (reduces bot-checks on batch runs).
#Set to None to download without cookies. Only used if COOKIES_FILE is not set below.
COOKIES_FROM_BROWSER = ("chrome",)

#Alternative to COOKIES_FROM_BROWSER: path to a Netscape-format cookies.txt file,
#e.g. exported with the "Get cookies.txt LOCALLY" browser extension. Reading a
#static file avoids yt-dlp's "Could not copy Chrome cookie database" error, which
#happens because cookiesfrombrowser can't read Chrome's cookie DB while Chrome is
#running (Chrome holds an exclusive lock on it) -- see
#https://github.com/yt-dlp/yt-dlp/issues/7271. If set, this takes priority over
#COOKIES_FROM_BROWSER so you don't have to keep your browser closed during a run.
COOKIES_FILE = r"C:\Users\aaron\Downloads\chromewebstore.google.com_cookies.txt"

#Clone Hero only recognizes a background video with exactly one of these
#lowercase filenames sitting directly in the song folder.
CANONICAL_VIDEO_NAMES = {"video.mp4", "video.avi", "video.webm", "video.ogv"}
#Markers yt-dlp leaves on partial/fragment files from an interrupted or
#not-yet-merged download (e.g. "video.f251.webm", "video.mp4.part", "video.temp.webm").
#These can't be safely repaired -- they need a re-download, not a rename/remux.
_YTDLP_FRAGMENT_RE = re.compile(r"\.f\d+\.|\.part$|\.ytdl$|\.temp\.", re.IGNORECASE)

try:
    from clonehero_video_offset import extract_audio, compute_offset, find_song_audio, find_video_file, probe_frame_rate, probe_video_codec, reencode_to_cfr
    OFFSET_SUPPORT = True
except ImportError as exc:
    OFFSET_SUPPORT = False
    print(f"Audio offset detection disabled (missing dependency: {exc}).")
    print("Run 'pip install audio-offset-finder numpy' and ensure ffmpeg is on PATH to enable it.")


def reset_search_failures() -> None:
    global search_failures
    search_failures = 0


def increment_search_failures() -> None:
    global search_failures
    search_failures += 1


def strip_title_noise(title: str) -> str:
    """Strip trailing noise patterns from song titles."""
    if not title:
        return title
    
    cleaned = title
    for pattern in (_TRAILING_DASH_NOISE_RE, _TRAILING_PAREN_NOISE_RE, _PEDAL_NOISE_RE):
        candidate = pattern.sub("", cleaned).strip()
        if candidate:
            cleaned = candidate

    cleaned = _PEDAL_IN_TITLE_RE.sub("", cleaned).strip()
    return cleaned


def is_difficulty_search_result(video_title: str) -> bool:
    """Return True when a video title appears to refer to chart difficulty rather than the song."""
    if not video_title:
        return False
    return bool(_DIFFICULTY_RESULT_RE.search(video_title))


def search_youtube_candidates(query: str, artist: str, title: str, max_results: int = 3) -> list[dict[str, str]]:
    """Search YouTube and return candidate videos filtered by title confidence and difficulty terms."""
    search_query = f"ytsearch{max_results}:{query}"
    ydl_search_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'socket_timeout': 30,
    }

    candidates: list[dict[str, str]] = []
    try:
        with yt_dlp.YoutubeDL(ydl_search_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)
            if info and 'entries' in info:
                for entry in info['entries']:
                    if not entry:
                        continue

                    video_title = entry.get('title', 'Unknown')
                    if is_difficulty_search_result(video_title):
                        continue

                    video_id = entry.get('id')
                    if not video_id:
                        continue

                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                    confidence, reason = calculate_confidence(video_title, artist, title)
                    candidates.append({
                        'url': video_url,
                        'title': video_title,
                        'confidence': confidence,
                        'reason': reason,
                    })
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        increment_search_failures()
        print(f"  WARNING: YouTube search failed for '{query}': {exc}")
        return []

    candidates.sort(key=lambda x: x['confidence'], reverse=True)
    return candidates


def parse_folder_name(folder_name: str) -> tuple[str, str]:
    """
    Parse Clone Hero folder name to extract artist and song title.
    Common patterns: "Artist - Song Title", "Song Title", "Artist-Song Title"
    Returns (artist, title) tuple. If no separator, returns ("", folder_name).
    """
    # Try to split on common separators
    if " - " in folder_name:
        parts = folder_name.split(" - ", 1)
        artist, title = parts[0].strip(), parts[1].strip()
    elif " -" in folder_name and folder_name.count(" -") == 1:
        parts = folder_name.split(" -", 1)
        artist, title = parts[0].strip(), parts[1].strip()
    elif "- " in folder_name and folder_name.count("- ") == 1:
        parts = folder_name.split("- ", 1)
        artist, title = parts[0].strip(), parts[1].strip()
    else:
        # No clear artist/title split, treat whole name as title
        artist, title = "", folder_name
    
    # Clean both parts
    artist = strip_title_noise(artist)
    title = strip_title_noise(title)
    
    return artist, title


def normalize_lookup_value(value: str) -> str:
    """Normalize artist/song values for matching against spreadsheet rows."""
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower()).strip()


def has_existing_video(song_folder: str) -> tuple[bool, Path | None]:
    """Return whether a song folder already contains a video file and the path to it."""
    folder = Path(song_folder)
    if not folder.exists():
        return False, None

    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in VIDEO_FILE_EXTENSIONS:
            return True, path
    return False, None


def scan_song_folder_video(song_dir: Path) -> dict[str, str]:
    """Inspect a song folder's video file(s) and repair common yt-dlp naming issues.

    Handles the double-extension files a literal (non-template) yt-dlp outtmpl
    produces when it has to remux mismatched codecs -- "video.mp4.webm" (genuine
    webm, just misnamed) and "video.mp4.mkv" (needs a real remux since Clone Hero
    doesn't read .mkv) -- plus wrong-case names and unrepairable partial fragments.

    Returns {'status': ..., 'detail': ...} where status is one of:
    'ok', 'no_video', 'fixed_rename', 'fixed_remux', 'broken_fragment',
    'unsupported_codec', 'remux_failed', 'unrecognized'.

    Only the first fixable file in a folder is repaired per call; a folder
    with multiple leftover variants gets cleaned up incrementally over
    successive scans (real libraries have at most one leftover per song).
    """
    relevant = sorted(
        p for p in song_dir.iterdir()
        if p.is_file() and p.name.lower().startswith("video.")
    )
    if not relevant:
        return {"status": "no_video", "detail": ""}

    for p in relevant:
        if p.name in CANONICAL_VIDEO_NAMES:
            if p.name.lower().endswith(".webm") and OFFSET_SUPPORT:
                #YouTube's "bestvideo[ext=webm]" is almost always VP9 now, which this
                #Clone Hero build cannot decode at all (confirmed via a real playtest).
                #Without this check, a pre-existing VP9 file would be accepted as "ok"
                #forever -- has_existing_video() would then always see a video present
                #and skip any future re-download, leaving it permanently broken.
                codec = probe_video_codec(p)
                if codec is not None and codec != "vp8":
                    p.unlink()
                    return {"status": "unsupported_codec", "detail": f"{p.name} ({codec}) removed -- needs a fresh download"}
            return {"status": "ok", "detail": p.name}

    for p in relevant:
        lower = p.name.lower()

        if _YTDLP_FRAGMENT_RE.search(lower):
            return {"status": "broken_fragment", "detail": p.name}

        if lower in CANONICAL_VIDEO_NAMES:
            target = song_dir / lower
            p.rename(target)
            return {"status": "fixed_rename", "detail": f"{p.name} -> {lower}"}

        if lower.endswith(".webm"):
            target = song_dir / "video.webm"
            p.rename(target)
            if OFFSET_SUPPORT:
                codec = probe_video_codec(target)
                if codec is not None and codec != "vp8":
                    target.unlink()
                    return {"status": "unsupported_codec", "detail": f"{p.name} ({codec}) removed -- needs a fresh download"}
            return {"status": "fixed_rename", "detail": f"{p.name} -> video.webm"}

        if lower.endswith(".mkv"):
            target = song_dir / "video.mp4"
            backup = song_dir / (p.name + ".bak")
            try:
                #Video stream copied bit-for-bit; only audio is transcoded (Opus-in-MP4
                #isn't reliably supported, but Clone Hero/most players handle AAC fine).
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(p), "-c:v", "copy", "-c:a", "aac", str(target)],
                    check=True, capture_output=True,
                )
            except Exception as exc:
                return {"status": "remux_failed", "detail": f"{p.name}: {exc}"}
            p.rename(backup)
            return {"status": "fixed_remux", "detail": f"{p.name} -> video.mp4 (original kept as {backup.name})"}

    return {"status": "unrecognized", "detail": ", ".join(p.name for p in relevant)}


def scan_and_fix_video_library(home_folder: str) -> None:
    """Scan every song folder under home_folder and repair common Clone Hero video naming issues."""
    print("=" * 70)
    print("SCANNING EXISTING VIDEO LIBRARY")
    print("=" * 70)

    counts: dict[str, int] = {}
    broken: list[str] = []
    bad_codec: list[str] = []

    for folder in sorted(Path(home_folder).iterdir()):
        if not folder.is_dir():
            continue

        result = scan_song_folder_video(folder)
        counts[result["status"]] = counts.get(result["status"], 0) + 1

        if result["status"] == "fixed_rename":
            print(f"  Renamed: {folder.name}: {result['detail']}")
        elif result["status"] == "fixed_remux":
            print(f"  Remuxed: {folder.name}: {result['detail']}")
        elif result["status"] == "broken_fragment":
            broken.append(folder.name)
        elif result["status"] == "unsupported_codec":
            bad_codec.append(folder.name)
            print(f"  Removed [unsupported codec]: {folder.name}: {result['detail']}")
        elif result["status"] in ("remux_failed", "unrecognized"):
            print(f"  WARNING [{result['status']}]: {folder.name}: {result['detail']}")

    print()
    print(
        f"Scan complete: {counts.get('ok', 0)} already correct, "
        f"{counts.get('fixed_rename', 0)} renamed, {counts.get('fixed_remux', 0)} remuxed, "
        f"{counts.get('no_video', 0)} without a video."
    )
    if broken:
        print(f"{len(broken)} broken/incomplete download fragment(s) need a re-download (not auto-fixable):")
        for name in broken:
            print(f"  - {name}")
    if bad_codec:
        print(f"{len(bad_codec)} video(s) removed for an unsupported codec (non-VP8 WebM, e.g. VP9/AV1) -- will be re-downloaded as MP4 on this run:")
        for name in bad_codec:
            print(f"  - {name}")
    print("=" * 70)
    print()


def load_existing_video_confidence(song_folder: str) -> int | None:
    """Load the stored confidence for a previously downloaded video, if available."""
    metadata_path = Path(song_folder) / VIDEO_METADATA_FILENAME
    if not metadata_path.exists():
        return None

    try:
        with metadata_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        confidence = data.get("confidence")
        return int(confidence) if confidence is not None else None
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def save_video_metadata(song_folder: str, confidence: int, url: str) -> None:
    """Persist metadata for the downloaded video so future runs can decide whether to replace it."""
    metadata_path = Path(song_folder) / VIDEO_METADATA_FILENAME
    metadata = {
        "confidence": confidence,
        "url": url,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


#Offset statuses that represent a completed, meaningful attempt -- re-running against
#the same video/audio without any change would just recompute the same result, so
#these are skipped on rerun. "error" is deliberately excluded: it represents an
#unexpected failure (ffmpeg crash, transient I/O error, etc.) that may not recur,
#so it's always retried on the next run.
SETTLED_OFFSET_STATUSES = ("written", "low_confidence", "no_reference_audio", "vfr_exceeds_window")


def load_offset_metadata(song_folder: str) -> dict | None:
    """Load the stored offset-detection result for a song folder, if available."""
    metadata_path = Path(song_folder) / VIDEO_METADATA_FILENAME
    if not metadata_path.exists():
        return None
    try:
        with metadata_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data.get("offset")
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def is_offset_settled(song_folder: str) -> bool:
    """Return True if a prior offset attempt already reached a settled status."""
    offset_meta = load_offset_metadata(song_folder)
    if not offset_meta:
        return False
    return offset_meta.get("status") in SETTLED_OFFSET_STATUSES


def save_offset_metadata(song_folder: str, offset_ms: int, confidence: float, status: str, source: str = "computed") -> None:
    """Persist an offset-detection result into video_meta.json, merging with existing fields.

    Merges rather than overwrites so this never clobbers the video-match confidence/url
    save_video_metadata() already wrote for the same folder. source is "computed" (the
    audio-correlation path) or "spreadsheet" (a pre-vetted offset from the lookup sheet)
    -- both are settled once written, but the source is worth keeping for the library report.
    """
    metadata_path = Path(song_folder) / VIDEO_METADATA_FILENAME
    metadata: dict = {}
    if metadata_path.exists():
        try:
            with metadata_path.open("r", encoding="utf-8") as handle:
                metadata = json.load(handle)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            metadata = {}

    metadata["offset"] = {
        "offset_ms": offset_ms,
        "confidence": confidence,
        "status": status,
        "source": source,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    #atomic write -- this file is also read by the video-match confidence logic, so a
    #half-written file from a crash mid-write would corrupt both concerns, not just this one.
    fd, tmp_path = tempfile.mkstemp(dir=song_folder, suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        os.replace(tmp_path, metadata_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


LIBRARY_REPORT_FILENAME = "library_status_report.csv"
LIBRARY_REPORT_FIELDNAMES = [
    "folder", "artist", "title",
    "has_video", "video_confidence",
    "has_offset", "offset_ms", "offset_confidence", "offset_status", "offset_source",
    "ch_score_status",
    "needs_review",
]
#Below this, a video match is treated as unconfirmed for reporting purposes. Not
#persisted anywhere -- the user's actual download-time threshold isn't stored in
#video_meta.json -- so this is a fixed, documented default independent of whatever
#threshold was used when the video was originally downloaded.
LOW_VIDEO_CONFIDENCE_THRESHOLD = 70


def _library_report_row(song_folder: Path) -> dict[str, object]:
    artist, title = parse_folder_name(song_folder.name)
    has_video, _ = has_existing_video(str(song_folder))
    video_confidence = load_existing_video_confidence(str(song_folder))
    offset_meta = load_offset_metadata(str(song_folder)) or {}
    offset_status = offset_meta.get("status", "")

    needs_review = (
        not has_video
        or video_confidence is None
        or video_confidence < LOW_VIDEO_CONFIDENCE_THRESHOLD
        or offset_status != "written"
    )

    return {
        "folder": song_folder.name,
        "artist": artist,
        "title": title,
        "has_video": has_video,
        "video_confidence": video_confidence if video_confidence is not None else "",
        "has_offset": bool(offset_meta),
        "offset_ms": offset_meta.get("offset_ms", ""),
        "offset_confidence": offset_meta.get("confidence", ""),
        "offset_status": offset_status,
        "offset_source": offset_meta.get("source", ""),
        #always "unknown" -- see the Task 9 spike outcome in SPEC.md: parsing scores.bin
        #would require also reverse-engineering the undocumented songcache.bin to resolve
        #its opaque song identifiers to folders, for very little real data on top of that
        "ch_score_status": "unknown",
        "needs_review": needs_review,
    }


def generate_library_report(home_folder: str, output_path: str | None = None) -> Path:
    """Scan every song folder under home_folder and write a CSV status report.

    Read-only -- this never writes to song.ini, video_meta.json, or any video file,
    it only reports on state earlier phases (search/download/offset) already wrote.
    """
    home = Path(home_folder)
    report_path = Path(output_path) if output_path else home / LIBRARY_REPORT_FILENAME

    rows = [_library_report_row(entry) for entry in sorted(home.iterdir()) if entry.is_dir()]

    fd, tmp_path = tempfile.mkstemp(dir=str(home), suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=LIBRARY_REPORT_FIELDNAMES)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        os.replace(tmp_path, report_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return report_path


def select_random_sample(items: list[dict[str, object]], sample_size: int = 3) -> list[dict[str, object]]:
    """Return a random sample of items for threshold review."""
    if sample_size <= 0:
        return list(items)
    # Ensure we always return a random selection. If sample_size >= len(items)
    # use random.sample with k=len(items) which returns a randomized permutation.
    k = min(sample_size, len(items))
    return random.sample(items, k)


def calculate_cochran_sample_size(
    population_size: int,
    confidence_level: float = 0.95,
    margin_of_error: float = 0.1,
    proportion: float = 0.5,
) -> int:
    """Calculate the Cochran sample size for the given population and confidence interval."""
    if population_size <= 0:
        return 0

    z_scores = {
        0.90: 1.645,
        0.95: 1.96,
        0.99: 2.576,
    }
    z = z_scores.get(confidence_level, 1.96)
    q = 1.0 - proportion
    n0 = (z**2 * proportion * q) / (margin_of_error**2)

    if population_size <= n0:
        corrected = n0 / (1 + ((n0 - 1) / population_size))
    else:
        corrected = n0

    return min(population_size, max(1, math.ceil(corrected)))


def summarize_confidence_statistics(confidence_values: list[int]) -> dict[str, object]:
    """Return descriptive statistics for a list of confidence scores."""
    if not confidence_values:
        return {
            'count': 0,
            'mean': 0.0,
            'median': 0.0,
            'mode': 'n/a',
            'std_dev': 0.0,
            'min': 0,
            'max': 0,
        }

    try:
        mode_value = statistics.mode(confidence_values)
    except statistics.StatisticsError:
        mode_value = 'multiple'

    std_dev = statistics.stdev(confidence_values) if len(confidence_values) > 1 else 0.0
    return {
        'count': len(confidence_values),
        'mean': statistics.mean(confidence_values),
        'median': statistics.median(confidence_values),
        'mode': mode_value,
        'std_dev': std_dev,
        'min': min(confidence_values),
        'max': max(confidence_values),
    }


def print_sample_confidence(sample_items: list[dict[str, object]], population_size: int, sample_size: int) -> None:
    """Print a sample of confidence ratings with statistics for threshold selection."""
    if not sample_items:
        return

    # Collect numeric confidences while ignoring None or invalid values
    confidence_values: list[int] = []
    for item in sample_items:
        try:
            val = item.get('confidence')
            if val is None:
                continue
            confidence_values.append(int(val))
        except (TypeError, ValueError):
            continue

    stats = summarize_confidence_statistics(confidence_values)

    print(f"Sampling {len(sample_items)} of {population_size} rated videos for threshold guidance.")
    print("Cochran sample size estimate for 95% confidence interval used to select the sample.")
    print("Confidence summary:")
    print(f"  Mean confidence: {stats['mean']:.1f}")
    print(f"  Median confidence: {stats['median']:.1f}")
    print(f"  Mode confidence: {stats['mode']}")
    print(f"  Std dev: {stats['std_dev']:.1f}")
    print(f"  Range: {stats['min']} - {stats['max']}")
    print("-" * 70)

    for item in sample_items:
        best_match = item.get("best_match") or {}
        conf = item.get('confidence')
        conf_display = f"{conf}/100" if conf is not None else "N/A"
        print(f"Folder: {item['folder']}")
        print(f"  Query: {item.get('query', '')}")
        print(f"  Best match: {best_match.get('title', 'N/A')}")
        print(f"  Confidence: {conf_display}")
        print(f"  Reason: {best_match.get('reason', 'no reason')}")
        print()


SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1QJ7wotWFoNNSwzIIIAGRcf4WAaYz1pXjhljYSk5h9DI/export?format=csv&gid=0"


def load_sheet_rows(spreadsheet_url: str = SPREADSHEET_URL) -> list[dict[str, str]]:
    """Load the public Google Sheets export as rows using the CSV export endpoint."""
    with urllib.request.urlopen(spreadsheet_url, timeout=30) as response:
        csv_text = response.read().decode("utf-8-sig")

    reader = csv.reader(io.StringIO(csv_text))
    header: list[str] | None = None
    rows: list[dict[str, str]] = []

    for raw_row in reader:
        values = [cell.strip() for cell in raw_row]
        if not values:
            continue

        normalized = [cell.lower() for cell in values]
        if header is None and "artist" in normalized and "song" in normalized and "offset" in normalized:
            header = values
            continue

        if header is None:
            continue

        row = {}
        for idx, column_name in enumerate(header):
            row[column_name] = values[idx] if idx < len(values) else ""

        if not any(cell for cell in row.values()):
            continue

        rows.append(row)

    return rows


def find_sheet_match(rows: list[dict[str, str]], search_artist: str, search_title: str) -> dict[str, str] | None:
    """Find the best spreadsheet row that matches the folder artist/title."""
    search_artist_norm = normalize_lookup_value(search_artist)
    search_title_norm = normalize_lookup_value(search_title)

    if not search_title_norm:
        return None

    best_match: dict[str, str] | None = None
    best_score = -1
    last_artist = ""

    for row in rows:
        artist = (row.get("Artist") or row.get("artist") or "").strip()
        title = (row.get("Song") or row.get("song") or "").strip()
        if not title:
            continue

        if artist:
            last_artist = artist
        elif last_artist:
            artist = last_artist

        artist_norm = normalize_lookup_value(artist)
        title_norm = normalize_lookup_value(title)
        score = 0

        if search_artist_norm and artist_norm:
            if search_artist_norm == artist_norm:
                score += 50
            elif search_artist_norm in artist_norm or artist_norm in search_artist_norm:
                score += 25

        if search_title_norm:
            if search_title_norm == title_norm:
                score += 50
            else:
                score += int(SequenceMatcher(None, search_title_norm, title_norm).ratio() * 30)

        if score > best_score:
            best_score = score
            best_match = row

    if best_score >= 50:
        return best_match
    return None


def extract_video_url(row: dict[str, str]) -> str | None:
    """Extract a direct video URL if a spreadsheet row includes one."""
    for key in ("Video URL", "URL", "YouTube URL", "Video Source", "Source URL", "Link"):
        value = row.get(key, "") or ""
        if not value:
            continue
        if "http" in value.lower():
            match = re.search(r"https?://\S+", value)
            if match:
                return match.group(0).rstrip(".,;:)")
    return None


def parse_offset(value: str | None) -> int | None:
    """Extract a numeric offset from a spreadsheet cell, if present."""
    if value is None:
        return None
    match = re.search(r"-?\d+", str(value))
    return int(match.group(0)) if match else None


_VIDEO_START_TIME_LINE_RE = re.compile(r"^([ \t]*)video_start_time([ \t]*=[ \t]*).*?(\r\n|\r|\n|$)", re.IGNORECASE)
_SONG_SECTION_LINE_RE = re.compile(r"^[ \t]*\[song\][ \t]*(\r\n|\r|\n|$)", re.IGNORECASE)


def patch_song_ini(song_folder: str, offset_ms: int) -> Path | None:
    """Write offset_ms to the song's video_start_time key, touching nothing else.

    Unlike the update_ini_with_offset() this replaces, it never matches the
    chart-internal offset/song_offset/video_offset keys -- only video_start_time,
    case-insensitively. Every other line is preserved byte-for-byte, including
    the file's existing CRLF-vs-LF convention. Writes atomically (temp file +
    os.replace) so a failure mid-write can't corrupt the ini.
    """
    folder = Path(song_folder)
    ini_files = sorted(folder.glob("*.ini"))
    if not ini_files:
        return None
    target = next((path for path in ini_files if path.name.lower() == "song.ini"), ini_files[0])

    #newline="" disables universal-newline translation -- without it, read_text()
    #silently converts CRLF to LF before we ever see it, corrupting the file's
    #existing line-ending convention on every write.
    with open(target, "r", encoding="utf-8", errors="ignore", newline="") as f:
        original = f.read()
    line_ending = "\r\n" if "\r\n" in original else "\n"

    if not original.strip():
        new_content = "[Song]{le}video_start_time = {offset}{le}".format(le=line_ending, offset=offset_ms)
    else:
        lines = original.splitlines(keepends=True)
        updated = False
        for i, line in enumerate(lines):
            match = _VIDEO_START_TIME_LINE_RE.match(line)
            if match:
                indent, equals, terminator = match.group(1), match.group(2), match.group(3)
                lines[i] = "{indent}video_start_time{eq}{offset}{term}".format(
                    indent=indent, eq=equals, offset=offset_ms, term=terminator
                )
                updated = True
                break

        if not updated:
            insert_at = None
            section_terminator = line_ending
            for i, line in enumerate(lines):
                match = _SONG_SECTION_LINE_RE.match(line)
                if match:
                    insert_at = i + 1
                    section_terminator = match.group(1) or line_ending
                    break

            if insert_at is not None:
                lines.insert(insert_at, "video_start_time = {offset}{term}".format(offset=offset_ms, term=section_terminator))
            else:
                if lines and not lines[-1].endswith(("\n", "\r")):
                    lines[-1] += line_ending
                lines.append("[Song]{le}".format(le=line_ending))
                lines.append("video_start_time = {offset}{le}".format(offset=offset_ms, le=line_ending))

        new_content = "".join(lines)

    fd, tmp_path = tempfile.mkstemp(dir=str(target.parent), suffix=".ini")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(new_content)
        os.replace(tmp_path, target)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return target


def apply_audio_offset(song_folder: str, dry_run: bool = False) -> bool:
    """Detect the audio/video sync offset for a freshly downloaded video and write it to the ini.

    Returns True if a confident offset was computed and written. Every attempt's
    outcome is persisted to video_meta.json (even failures/low-confidence results),
    and a prior settled result is skipped on rerun -- see SETTLED_OFFSET_STATUSES.

    When dry_run is True, VFR detection/extraction/compute_offset() still run (so
    the user sees what would happen) but nothing is written: no CFR re-encode
    overwrite, no song.ini patch, no video_meta.json persistence.
    """
    if not OFFSET_SUPPORT:
        return False

    if is_offset_settled(song_folder):
        return False

    folder = Path(song_folder)
    video_path = find_video_file(folder)
    if video_path is None:
        return False

    audio_path = find_song_audio(folder)
    if audio_path is None:
        print(f"  Skipping offset detection: no usable full-mix audio found in {folder.name}")
        if not dry_run:
            save_offset_metadata(song_folder, offset_ms=0, confidence=0.0, status="no_reference_audio")
        return False

    if probe_frame_rate(video_path):
        if dry_run:
            print(f"  [dry-run] Variable frame rate detected in {video_path.name}; would re-encode to constant frame rate (skipped).")
        else:
            print(f"  Variable frame rate detected in {video_path.name}; re-encoding to constant frame rate...")
            if not reencode_to_cfr(video_path):
                print(f"  Skipping offset detection: CFR re-encode failed for {video_path.name}")
                save_offset_metadata(song_folder, offset_ms=0, confidence=0.0, status="error")
                return False
            print(f"  Re-encoded {video_path.name} to constant frame rate.")

    temp_wav = folder / "_offset_temp.wav"
    try:
        if not extract_audio(video_path, temp_wav):
            print(f"  Skipping offset detection: ffmpeg could not extract audio from {video_path.name}")
            if not dry_run:
                save_offset_metadata(song_folder, offset_ms=0, confidence=0.0, status="error")
            return False

        result = compute_offset(audio_path, temp_wav)
        if result["status"] != "ok":
            print(f"  Skipping offset detection: {result['status']} (confidence={result['confidence_ratio']:.2f})")
            if not dry_run:
                save_offset_metadata(song_folder, offset_ms=result["offset_ms"], confidence=result["confidence_ratio"], status=result["status"])
            return False

        offset_ms = result["offset_ms"]
        if dry_run:
            print(f"  [dry-run] Would set video_start_time = {offset_ms} (confidence={result['confidence_ratio']:.2f}) -- not written.")
            return False

        updated_ini = patch_song_ini(song_folder, offset_ms)
        if updated_ini is not None:
            print(f"  Detected audio offset {offset_ms}ms (confidence={result['confidence_ratio']:.2f}); updated {updated_ini.name}")
            save_offset_metadata(song_folder, offset_ms=offset_ms, confidence=result["confidence_ratio"], status="written")
            return True
        save_offset_metadata(song_folder, offset_ms=offset_ms, confidence=result["confidence_ratio"], status="error")
        return False
    finally:
        temp_wav.unlink(missing_ok=True)


def calculate_confidence(video_title: str, search_artist: str, search_title: str) -> tuple[int, str]:
    """
    Calculate confidence score (0-100) for how well a video matches the search.
    Returns (score, reason).
    """
    video_title_lower = video_title.lower()
    search_title_lower = search_title.lower()
    search_artist_lower = search_artist.lower() if search_artist else ""
    
    score = 0
    reasons = []
    
    # Check for exact artist and title match
    if search_artist and search_artist_lower in video_title_lower:
        score += 30
        reasons.append("artist match")
    
    # Calculate title similarity using SequenceMatcher
    title_similarity = SequenceMatcher(None, search_title_lower, video_title_lower).ratio()
    if title_similarity > 0.8:
        score += 40
        reasons.append(f"high title similarity ({int(title_similarity*100)}%)")
    elif title_similarity > 0.6:
        score += 25
        reasons.append(f"good title similarity ({int(title_similarity*100)}%)")
    elif title_similarity > 0.4:
        score += 15
        reasons.append(f"moderate title similarity ({int(title_similarity*100)}%)")
    
    # Bonus for "official" in title
    if "official" in video_title_lower:
        score += 20
        reasons.append("marked as official")
    
    # Bonus for "music video" or "mv"
    if "music video" in video_title_lower or "(mv)" in video_title_lower:
        score += 10
        reasons.append("labeled as music video")
    
    # Penalty for covers, live versions, remixes (unless that's what we searched for)
    if "cover" in video_title_lower and "cover" not in search_title_lower:
        score -= 20
        reasons.append("cover version")
    if "live" in video_title_lower and "live" not in search_title_lower:
        score -= 15
        reasons.append("live version")
    if "remix" in video_title_lower and "remix" not in search_title_lower:
        score -= 10
        reasons.append("remix version")
    
    # Clamp score between 0-100
    score = max(0, min(100, score))
    
    reason_str = ", ".join(reasons) if reasons else "no match indicators"
    return score, reason_str


def prompt_library_path(default: str, interactive: bool = False) -> str:
    """Prompt for the Clone Hero songs library folder, falling back to default
    unless interactivity is explicitly requested (matches prompt_confidence_threshold)."""
    if not interactive or not sys.stdin.isatty():
        return default

    entered = input(f"Enter your Clone Hero songs library path (or press Enter for {default}): ").strip()
    return entered if entered else default


def poll_typed_confidence(buffer: str) -> tuple[str, str | None]:
    """Non-blocking check for a typed line on stdin (Windows only, via msvcrt).

    Lets the sampling loop react to a typed confidence value between search
    iterations without ever blocking on input() -- the only alternative would
    be a background thread doing blocking input(), which would still be alive
    (and competing for stdin) when prompt_confidence_threshold() later makes
    its own input() call on the non-early-exit path, since a thread blocked in
    input() can't be cleanly cancelled.

    Returns (updated_buffer, completed_line). completed_line is only non-None
    once Enter has been pressed; on non-Windows platforms (no msvcrt) this is
    a no-op that always returns (buffer, None) unchanged.
    """
    if msvcrt is None:
        return buffer, None
    while msvcrt.kbhit():
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            print()
            return "", buffer
        if ch == "\x08":
            if buffer:
                buffer = buffer[:-1]
                sys.stdout.write("\b \b")
                sys.stdout.flush()
        elif ch == "\x03":
            raise KeyboardInterrupt
        else:
            buffer += ch
            sys.stdout.write(ch)
            sys.stdout.flush()
    return buffer, None


def prompt_confidence_threshold(
    default: int = 70,
    sample_items: list[dict[str, object]] | None = None,
    sample_size: int = 0,
    interactive: bool = False,
) -> int:
    """Prompt for the confidence threshold, but fall back to the default unless interactivity is explicitly requested."""
    if sample_items and interactive and sys.stdin.isatty():
        total_rated = len(sample_items)
        target_sample_size = calculate_cochran_sample_size(total_rated)
        if sample_size > 0:
            target_sample_size = min(target_sample_size, sample_size)

        actual_sample_size = min(total_rated, target_sample_size)
        sampled_items = select_random_sample(sample_items, sample_size=actual_sample_size)
        print_sample_confidence(sampled_items, population_size=total_rated, sample_size=actual_sample_size)

    if not interactive or not sys.stdin.isatty():
        print(f"Using default confidence threshold: {default}")
        return default

    while True:
        threshold_input = input(f"Enter minimum confidence to auto-download without verification (0-100, or press Enter for {default}): ").strip()
        if threshold_input == "":
            return default
        try:
            confidence_threshold = int(threshold_input)
            if 0 <= confidence_threshold <= 100:
                return confidence_threshold
            print("Please enter a number between 0 and 100.")
        except ValueError:
            print("Please enter a valid number.")


def download_video_if_needed(url: str, currentSongFileFolder: str, candidate_confidence: int | None) -> bool:
    """Download a video into a song folder and save metadata if successful."""
    #Force codec-compatible pairs so yt-dlp merges into video.mp4 or video.webm --
    #never a mismatched mp4-video/opus-audio pair, which yt-dlp can only hold in .mkv
    #(Clone Hero doesn't recognize .mkv, and a literal "video.mp4" outtmpl lets
    #yt-dlp tack the real extension on top of it, producing "video.mp4.mkv"/"video.mp4.webm").
    #MP4 first, confirmed working: a WebM-first attempt was tried and reverted after
    #real playtesting showed Clone Hero throwing "Unsupported video codec 'VP9'" and
    #never rendering the video at all -- YouTube's "bestvideo[ext=webm]" is virtually
    #always VP9 now (VP8 is largely gone from current uploads), and this Clone Hero
    #build only decodes VP8 webm, not VP9. The webm fallback below is constrained to
    #vcodec=vp8 specifically so it can never again silently grab an incompatible VP9
    #stream -- in practice this fallback will rarely match anything on modern YouTube
    #videos, which is fine: MP4 is the confirmed-working default.
    ydl_opts = {
        'outtmpl': os.path.join(currentSongFileFolder, 'video.%(ext)s'),
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=webm][vcodec=vp8]+bestaudio[ext=webm]/best[ext=mp4]/best[ext=webm][vcodec=vp8]/best',
        'overwrites': False,
        'noplaylist': 1,
    }
    if COOKIES_FILE:
        ydl_opts['cookiefile'] = COOKIES_FILE
    elif COOKIES_FROM_BROWSER:
        ydl_opts['cookiesfrombrowser'] = COOKIES_FROM_BROWSER
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if candidate_confidence is not None:
            save_video_metadata(currentSongFileFolder, candidate_confidence, url)
        return True
    except Exception as e:
        print(f"  ERROR: Download failed for {currentSongFileFolder}: {e}")
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Clone Hero videos based on song folders and spreadsheet metadata.")
    parser.add_argument("--library-path", type=str, default=None, help="Path to your Clone Hero songs library folder. Skips the startup prompt when set.")
    parser.add_argument("--threshold", type=int, default=None, help="Minimum confidence required to auto-download without confirmation.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--interactive", action="store_true", dest="interactive", help="Prompt for the confidence threshold.")
    group.add_argument("--no-interactive", action="store_false", dest="interactive", help="Skip the confidence prompt and use the default threshold.")
    parser.set_defaults(interactive=True)
    parser.add_argument(
        "--sample-size",
        type=int,
        default=0,
        help="Maximum number of rated songs to sample before asking for a threshold; Cochran's 95%% CI formula determines the ideal sample size when this is 0.",
    )
    parser.add_argument(
        "--skip-library-scan",
        action="store_true",
        help="Skip the startup scan that repairs mis-named/mis-muxed video files already in your library.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and log offsets without writing to song.ini, re-encoding any video, or updating video_meta.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    #Falls back to this default (press Enter at the prompt to accept it) unless
    #--library-path was passed, or the prompt is skipped (non-interactive/non-tty).
    homeFolder = args.library_path or prompt_library_path(DEFAULT_HOME_FOLDER, interactive=args.interactive)

    # Validate that the home folder exists
    if not os.path.exists(homeFolder):
        print(f"ERROR: Home folder does not exist: {homeFolder}")
        print("Re-run and enter a valid path, or pass --library-path <path>.")
        input("Press Enter to exit...")
        exit(1)

    if not os.path.isdir(homeFolder):
        print(f"ERROR: Path is not a directory: {homeFolder}")
        input("Press Enter to exit...")
        exit(1)

    os.chdir(homeFolder)
    print(os.getcwd())
    print()

    if not args.skip_library_scan:
        scan_and_fix_video_library(homeFolder)

    # Ask user for confidence threshold
    print("=" * 70)
    print("CONFIDENCE VERIFICATION SETTINGS")
    print("=" * 70)
    print("Videos will be rated 0-100 based on how well they match your search.")
    print("You can choose to verify videos below a certain confidence level.")
    print()
    print("Confidence levels:")
    print("  90-100: Very high confidence (exact artist + title match, official)")
    print("  70-89:  High confidence (good match, may be official)")
    print("  50-69:  Medium confidence (partial match)")
    print("  0-49:   Low confidence (weak match, likely wrong video)")
    print()

    default_threshold = args.threshold if args.threshold is not None else 70
    reset_search_failures()

    # First pass: rate all song folders without downloading.
    print("Preparing confidence ratings for all song folders...")
    sheet_rows: list[dict[str, str]] = []
    total_songs = 0
    skipped = 0
    try:
        sheet_rows = load_sheet_rows()
        print(f"Loaded {len(sheet_rows)} spreadsheet rows for matching.")
    except Exception as e:
        print(f"Warning: Unable to load spreadsheet: {e}")

    # Collect folder entries first (no network calls) so we can sample before rating
    folder_entries: list[dict[str, object]] = []
    for file in sorted(os.listdir()):
        if not os.path.isdir(file):
            continue

        artist, title = parse_folder_name(file)

        if not artist and not title:
            print(f"Skipping folder (couldn't parse name): {file}")
            skipped += 1
            continue

        if artist and title:
            query = f"{artist} {title}"
        else:
            query = title

        # Defer spreadsheet matching until after sampling and threshold selection
        sheet_match = None

        folder_entries.append({
            'folder': file,
            'artist': artist,
            'title': title,
            'query': query,
            'sheet_match': sheet_match,
            'song_folder': os.path.join(homeFolder, file),
        })

    # Population size for sampling
    population_size = len(folder_entries)
    total_songs = population_size + skipped

    # Determine sample size (Cochran estimate unless user provided)
    if args.sample_size and args.sample_size > 0:
        target_sample_size = min(population_size, args.sample_size)
    else:
        target_sample_size = calculate_cochran_sample_size(population_size)

    actual_sample_size = min(population_size, target_sample_size)

    sampled_entries = select_random_sample(folder_entries, sample_size=actual_sample_size)

    # Lets the user type a confidence level at any point during sampling instead of
    # always waiting for the whole sample to finish -- see poll_typed_confidence().
    allow_typed_confidence = args.interactive and sys.stdin.isatty() and msvcrt is not None
    if allow_typed_confidence:
        print("(You can type a confidence level (0-100) and press Enter at any time during sampling to stop early and use it as the threshold.)")
    typed_buffer = ""
    entered_threshold: int | None = None

    # Rate only the sampled entries to guide threshold selection
    sampled_items: list[dict[str, object]] = []
    for entry in sampled_entries:
        file = entry['folder']
        artist = entry['artist']
        title = entry['title']
        query = entry['query']
        sheet_match = entry['sheet_match']
        currentSongFileFolder = entry['song_folder']

        url = None
        candidate_confidence: int | None = None
        url_source = 'search'
        candidates: list[dict[str, object]] = []
        best_match: dict[str, object] = {}

        if sheet_match is not None:
            url = extract_video_url(sheet_match)
            if url:
                candidate_confidence = 95
                url_source = 'spreadsheet'
                best_match = {
                    'url': url,
                    'title': 'Spreadsheet URL',
                    'confidence': candidate_confidence,
                    'reason': 'spreadsheet override',
                }

        if url is None:
            print(f"Sampling search YouTube for: {query}")
            try:
                candidates = search_youtube_candidates(query, artist, title)
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as exc:
                increment_search_failures()
                print(f"  WARNING: YouTube search failed for '{query}': {exc}")
                candidates = []

            if candidates:
                best_match = candidates[0]
                candidate_confidence = best_match['confidence']
                url = best_match['url']

        sampled_items.append({
            'folder': file,
            'artist': artist,
            'title': title,
            'query': query,
            'sheet_match': sheet_match,
            'best_match': best_match,
            'candidates': candidates,
            'confidence': candidate_confidence,
            'url': url,
            'url_source': url_source,
            'song_folder': currentSongFileFolder,
        })

        if allow_typed_confidence:
            typed_buffer, typed_line = poll_typed_confidence(typed_buffer)
            if typed_line is not None:
                typed_line = typed_line.strip()
                if typed_line == "":
                    pass
                else:
                    try:
                        candidate_value = int(typed_line)
                        if 0 <= candidate_value <= 100:
                            entered_threshold = candidate_value
                            print(f"Confidence level {entered_threshold} entered -- ending sampling early.")
                            break
                        print(f"'{typed_line}' is outside 0-100 -- ignored, continuing sampling.")
                    except ValueError:
                        print(f"'{typed_line}' isn't a valid number -- ignored, continuing sampling.")

    # Show sample statistics and prompt for threshold
    print_sample_confidence(sampled_items, population_size=population_size, sample_size=actual_sample_size)

    if entered_threshold is not None:
        confidence_threshold = entered_threshold
        print(f"Using confidence threshold entered during sampling: {confidence_threshold}")
    else:
        confidence_threshold = prompt_confidence_threshold(
            default=default_threshold,
            sample_items=None,
            sample_size=0,
            interactive=args.interactive,
        )

    # Run spreadsheet indexing AFTER sampling and after the user has selected a threshold.
    # This gives the user a chance to choose threshold before spreadsheet overrides
    # are applied to downloads.
    if sheet_rows:
        for entry in folder_entries:
            try:
                match = find_sheet_match(sheet_rows, entry['artist'], entry['title'])
            except Exception:
                match = None
            if match is not None:
                entry['sheet_match'] = match
                print(f"Found spreadsheet entry for: {entry['artist']} - {entry['title']}")
                print(f"  Offset: {match.get('Offset', '')}")

    print(f"\nVideos with confidence >= {confidence_threshold} will download automatically.")
    print(f"Videos with confidence < {confidence_threshold} will require your confirmation after all candidates are rated.")
    print()
    print("=" * 70)
    print()

    # Stats tracking
    downloaded = 0
    low_confidence_queue: list[dict[str, object]] = []

    # Map sampled results so we don't re-run searches for those
    sample_map = {item['folder']: item for item in sampled_items}

    # If any folder has a spreadsheet override, apply it to sampled results so
    # the spreadsheet URL takes precedence for immediate downloads.
    for entry in folder_entries:
        folder_name = entry['folder']
        sheet_match = entry.get('sheet_match')
        if not sheet_match:
            continue
        url = extract_video_url(sheet_match)
        if not url:
            continue
        if folder_name in sample_map:
            sampled_entry = sample_map[folder_name]
            sampled_entry['url'] = url
            sampled_entry['confidence'] = 95
            sampled_entry['url_source'] = 'spreadsheet'
            sampled_entry['best_match'] = {
                'url': url,
                'title': 'Spreadsheet URL',
                'confidence': 95,
                'reason': 'spreadsheet override',
            }

    try:
        for entry in folder_entries:
            file = entry['folder']
            artist = entry['artist']
            title = entry['title']
            query = entry['query']
            sheet_match = entry['sheet_match']
            currentSongFileFolder = entry['song_folder']

            # Use sampled result when available
            if file in sample_map:
                item = sample_map[file]
            else:
                url = None
                candidate_confidence: int | None = None
                url_source = 'search'
                candidates: list[dict[str, object]] = []
                best_match: dict[str, object] = {}

                if sheet_match is not None:
                    url = extract_video_url(sheet_match)
                    if url:
                        candidate_confidence = 95
                        url_source = 'spreadsheet'
                        best_match = {
                            'url': url,
                            'title': 'Spreadsheet URL',
                            'confidence': candidate_confidence,
                            'reason': 'spreadsheet override',
                        }

                if url is None:
                    print(f"Searching YouTube for: {query}")
                    try:
                        candidates = search_youtube_candidates(query, artist, title)
                    except (KeyboardInterrupt, SystemExit):
                        raise
                    except BaseException as exc:
                        increment_search_failures()
                        print(f"  WARNING: YouTube search failed for '{query}': {exc}")
                        candidates = []

                    if candidates:
                        best_match = candidates[0]
                        candidate_confidence = best_match['confidence']
                        url = best_match['url']

                item = {
                    'folder': file,
                    'artist': artist,
                    'title': title,
                    'query': query,
                    'sheet_match': sheet_match,
                    'best_match': best_match,
                    'candidates': candidates,
                    'confidence': candidate_confidence,
                    'url': url,
                    'url_source': url_source,
                    'song_folder': currentSongFileFolder,
                }

            # Immediately act on high-confidence matches
            if item['confidence'] is None or item['url'] is None:
                print(f"Skipping {item['folder']} because no rated video was available.")
                skipped += 1
                continue

            print(f"Processing {item['folder']}")
            candidate_confidence = item['confidence']
            url = item['url']
            sheet_match = item['sheet_match']

            if candidate_confidence < confidence_threshold:
                print(f"  ⚠️  Candidate below threshold ({candidate_confidence} < {confidence_threshold})")
                print(f"  Song: {item['artist']} - {item['title']}" if item['artist'] else f"  Song: {item['title']}")
                print("  Top candidates:")
                for i, cand in enumerate(item['candidates'], 1):
                    print(f"    {i}. [{cand['confidence']}%] {cand['title']}")
                print()
                low_confidence_queue.append(item)
                continue

            print(f"  ✓ High confidence - ready to download")
            print()

            if not os.path.exists(currentSongFileFolder):
                try:
                    os.makedirs(currentSongFileFolder, exist_ok=True)
                except Exception as e:
                    print(f"  ERROR: Cannot access folder {item['folder']}: {e}")
                    skipped += 1
                    continue

            existing_video, existing_video_path = has_existing_video(currentSongFileFolder)
            if existing_video:
                existing_confidence = load_existing_video_confidence(currentSongFileFolder)
                if candidate_confidence is None or existing_confidence is None or candidate_confidence <= existing_confidence:
                    print(f"  Existing video already present at {existing_video_path.name}; skipping replacement.")
                    skipped += 1
                    continue
                print(f"  Existing video found with lower confidence ({existing_confidence}); replacing it with a higher-confidence match ({candidate_confidence}).")

            if download_video_if_needed(url, currentSongFileFolder, candidate_confidence):
                downloaded += 1
                print(f"Downloaded video for: {item['folder']}\n")
            else:
                skipped += 1
                continue

            offset_from_sheet = False
            if sheet_match is not None:
                if is_offset_settled(currentSongFileFolder):
                    offset_from_sheet = True
                else:
                    offset = parse_offset(sheet_match.get('Offset'))
                    if offset is not None:
                        if args.dry_run:
                            print(f"[dry-run] Would update song.ini with offset {offset} (spreadsheet) -- not written.")
                            offset_from_sheet = True
                        else:
                            updated_ini = patch_song_ini(currentSongFileFolder, offset)
                            if updated_ini is not None:
                                print(f"Updated {updated_ini.name} with offset {offset} (spreadsheet)")
                                save_offset_metadata(currentSongFileFolder, offset_ms=offset, confidence=None, status="written", source="spreadsheet")
                                offset_from_sheet = True
                    else:
                        print("Spreadsheet match found but no numeric offset was available.")

            if not offset_from_sheet:
                apply_audio_offset(currentSongFileFolder, dry_run=args.dry_run)

        if low_confidence_queue:
            print("=" * 70)
            print("LOW-CONFIDENCE REVIEW")
            print("=" * 70)
            print("Review low-confidence matches after all high-confidence downloads have completed.")
            print()

            for item in low_confidence_queue:
                print(f"Song folder: {item['folder']}")
                print(f"Best candidate: {item['best_match']['title']}")
                print(f"Confidence: {item['confidence']}/100 ({item['best_match']['reason']})")
                print(f"URL: {item['url']}")
                print()
                while True:
                    user_choice = input("  Download this video? (y=yes, n=skip, 1-3=pick different result, url=enter custom URL): ").strip().lower()
                    if user_choice == 'y':
                        chosen_url = item['url']
                        chosen_confidence = item['confidence']
                        break
                    elif user_choice == 'n':
                        print(f"  Skipping: {item['folder']}")
                        chosen_url = None
                        chosen_confidence = None
                        skipped += 1
                        break
                    elif user_choice in ['1', '2', '3']:
                        idx = int(user_choice) - 1
                        if idx < len(item['candidates']):
                            chosen = item['candidates'][idx]
                            chosen_url = chosen['url']
                            chosen_confidence = chosen['confidence']
                            print(f"  Using: {chosen['title']}")
                            break
                        else:
                            print("  Invalid choice, please try again.")
                    elif user_choice == 'url':
                        custom_url = input("  Enter YouTube URL: ").strip()
                        if 'youtube.com/watch' in custom_url or 'youtu.be/' in custom_url:
                            chosen_url = custom_url
                            chosen_confidence = 100
                            print(f"  Using custom URL: {custom_url}")
                            break
                        else:
                            print("  Invalid YouTube URL, please try again.")
                    else:
                        print("  Invalid choice, please enter y, n, 1-3, or url.")

                if not chosen_url:
                    print()
                    continue

                if not os.path.exists(item['song_folder']):
                    try:
                        os.makedirs(item['song_folder'], exist_ok=True)
                    except Exception as e:
                        print(f"  ERROR: Cannot access folder {item['folder']}: {e}")
                        skipped += 1
                        continue

                existing_video, existing_video_path = has_existing_video(item['song_folder'])
                if existing_video:
                    existing_confidence = load_existing_video_confidence(item['song_folder'])
                    if chosen_confidence is None or existing_confidence is None or chosen_confidence <= existing_confidence:
                        print(f"  Existing video already present at {existing_video_path.name}; skipping replacement.")
                        skipped += 1
                        print()
                        continue
                    print(f"  Existing video found with lower confidence ({existing_confidence}); replacing it with a higher-confidence match ({chosen_confidence}).")

                if download_video_if_needed(chosen_url, item['song_folder'], chosen_confidence):
                    downloaded += 1
                    print(f"Downloaded video for: {item['folder']}\n")
                else:
                    skipped += 1
                    print()
                    continue

                offset_from_sheet = False
                if item['sheet_match'] is not None:
                    if is_offset_settled(item['song_folder']):
                        offset_from_sheet = True
                    else:
                        offset = parse_offset(item['sheet_match'].get('Offset'))
                        if offset is not None:
                            if args.dry_run:
                                print(f"[dry-run] Would update song.ini with offset {offset} (spreadsheet) -- not written.")
                                offset_from_sheet = True
                            else:
                                updated_ini = patch_song_ini(item['song_folder'], offset)
                                if updated_ini is not None:
                                    print(f"Updated {updated_ini.name} with offset {offset} (spreadsheet)")
                                    save_offset_metadata(item['song_folder'], offset_ms=offset, confidence=None, status="written", source="spreadsheet")
                                    offset_from_sheet = True
                        else:
                            print("Spreadsheet match found but no numeric offset was available.")

                if not offset_from_sheet:
                    apply_audio_offset(item['song_folder'], dry_run=args.dry_run)

    except KeyboardInterrupt:
        print("\n\nScript interrupted by user (Ctrl+C)")
        print("Generating partial summary...\n")
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        print("Generating partial summary...\n")
    finally:
        # Print summary
        print()
        print("=" * 70)
        print("DOWNLOAD SUMMARY")
        print("=" * 70)
        print(f"Total songs processed: {total_songs}")
        print(f"Videos downloaded: {downloaded}")
        print(f"Songs skipped: {skipped}")
        if search_failures:
            print(f"Search failures encountered: {search_failures}")
        if total_songs > 0:
            print(f"Success rate: {(downloaded/total_songs*100):.1f}%")
        else:
            print("Success rate: N/A")
        print("=" * 70)


if __name__ == "__main__":
    main()
	
