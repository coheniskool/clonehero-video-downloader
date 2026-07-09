#import youtube-dl
from __future__ import unicode_literals
import yt_dlp

import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

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
    except Exception:
        pass

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


def update_ini_with_offset(song_folder: str, offset: int) -> Path | None:
    """Update the first matching .ini file in a song folder with the provided offset."""
    folder = Path(song_folder)
    ini_files = sorted(folder.glob("*.ini"))
    if not ini_files:
        return None

    target = next((path for path in ini_files if path.name.lower() == "song.ini"), ini_files[0])
    content = target.read_text(encoding="utf-8", errors="ignore")

    if not content.strip():
        content = "[Song]\nvideo_start_time = {offset}\n"
    else:
        updated = False
        for key in ("video_start_time", "offset", "song_offset", "video_offset"):
            pattern = re.compile(rf"(?im)^(\s*{re.escape(key)}\s*=)\s*.*$")
            if pattern.search(content):
                content = pattern.sub(rf"\g<1> {offset}", content, count=1)
                updated = True
                break

        if not updated:
            if re.search(r"(?im)^\s*\[Song\]\s*$", content):
                content = re.sub(
                    r"(?im)(^\s*\[Song\]\s*$)",
                    rf"\1\nvideo_start_time = {offset}",
                    content,
                    count=1,
                )
            else:
                content += f"\n[Song]\nvideo_start_time = {offset}\n"

    target.write_text(content, encoding="utf-8")
    return target


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


def prompt_confidence_threshold(default: int = 70, interactive: bool = False) -> int:
    """Prompt for the confidence threshold, but fall back to the default unless interactivity is explicitly requested."""
    if not interactive or not sys.stdin.isatty():
        print(f"Using default confidence threshold: {default}")
        return default

    while True:
        threshold_input = input("Enter minimum confidence to auto-download without verification (0-100, or press Enter for 70): ").strip()
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
    ydl_opts = {
        'outtmpl': os.path.join(currentSongFileFolder, 'video.mp4'),
        'nooverwrites': 0,
        'noplaylist': 1,
    }
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
    parser.add_argument("--threshold", type=int, default=None, help="Minimum confidence required to auto-download without confirmation.")
    parser.add_argument("--interactive", action="store_true", help="Prompt for the confidence threshold even in a terminal session.")
    return parser.parse_args()


def main() -> None:
    #CHANGE THE HOME FOLDER TO THE FOLDER PATH YOU WANT TO DOWNLOAD SONGS FOR
    homeFolder = r"M:\_Organized\Songs"

    # Validate that the home folder exists
    if not os.path.exists(homeFolder):
        print(f"ERROR: Home folder does not exist: {homeFolder}")
        print("Please update the homeFolder path in the script.")
        input("Press Enter to exit...")
        exit(1)

    if not os.path.isdir(homeFolder):
        print(f"ERROR: Path is not a directory: {homeFolder}")
        input("Press Enter to exit...")
        exit(1)

    os.chdir(homeFolder)
    print(os.getcwd())
    print()

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

    args = parse_args()
    confidence_threshold = prompt_confidence_threshold(default=args.threshold if args.threshold is not None else 70, interactive=args.interactive)

    print(f"\nVideos with confidence >= {confidence_threshold} will download automatically.")
    print(f"Videos with confidence < {confidence_threshold} will require your confirmation after all candidates are rated.")
    print()
    print("=" * 70)
    print()

    # Stats tracking
    total_songs = 0
    downloaded = 0
    skipped = 0

    low_confidence_queue: list[dict[str, object]] = []

    sheet_rows: list[dict[str, str]] = []
    try:
        sheet_rows = load_sheet_rows()
        print(f"Loaded {len(sheet_rows)} spreadsheet rows for matching.")
    except Exception as e:
        print(f"Warning: Unable to load spreadsheet: {e}")

    try:
        for file in os.listdir():
            if not os.path.isdir(file):
                continue

            total_songs += 1
            artist, title = parse_folder_name(file)

            if artist and title:
                query = f"{artist} {title}"
            elif title:
                query = title
            else:
                print(f"Skipping folder (couldn't parse name): {file}")
                skipped += 1
                continue

            sheet_match = None
            if sheet_rows:
                sheet_match = find_sheet_match(sheet_rows, artist, title)
                if sheet_match is not None:
                    print(f"Found spreadsheet entry for: {artist} - {title}")
                    print(f"  Offset: {sheet_match.get('Offset', '')}")

            url = None
            candidate_confidence: int | None = None
            url_source = "search"
            currentSongFileFolder = os.path.join(homeFolder, file)

            if sheet_match is not None:
                url = extract_video_url(sheet_match)
                if url:
                    candidate_confidence = 95
                    url_source = "spreadsheet"
                    print(f"  Using spreadsheet URL: {url}")

            if url is None:
                print(f"Searching YouTube for: {query}")
                candidates = search_youtube_candidates(query, artist, title)

                if not candidates:
                    print(f"No suitable music video found for: {file}")
                    skipped += 1
                    continue

                best_match = candidates[0]
                candidate_confidence = best_match['confidence']
                url = best_match['url']

                print(f"  Best match: {best_match['title']}")
                print(f"  Confidence: {candidate_confidence}/100 ({best_match['reason']})")
                print(f"  URL: {url}")

                if candidate_confidence < confidence_threshold:
                    print(f"  ⚠️  Confidence below threshold ({candidate_confidence} < {confidence_threshold})")
                    print(f"  Song: {artist} - {title}" if artist else f"  Song: {title}")
                    print("  Top candidates:")
                    for i, cand in enumerate(candidates, 1):
                        print(f"    {i}. [{cand['confidence']}%] {cand['title']}")
                    print()
                    low_confidence_queue.append({
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
                    continue
                else:
                    print(f"  ✓ High confidence - auto-downloading")
                    print()

            if not os.path.exists(currentSongFileFolder):
                try:
                    os.makedirs(currentSongFileFolder, exist_ok=True)
                except Exception as e:
                    print(f"  ERROR: Cannot access folder {file}: {e}")
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
                print(f"Downloaded video for: {file}\n")
            else:
                skipped += 1
                continue

            if sheet_match is not None:
                offset = parse_offset(sheet_match.get('Offset'))
                if offset is not None:
                    updated_ini = update_ini_with_offset(currentSongFileFolder, offset)
                    if updated_ini is not None:
                        print(f"Updated {updated_ini.name} with offset {offset}")
                else:
                    print("Spreadsheet match found but no numeric offset was available.")

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

                if item['sheet_match'] is not None:
                    offset = parse_offset(item['sheet_match'].get('Offset'))
                    if offset is not None:
                        updated_ini = update_ini_with_offset(item['song_folder'], offset)
                        if updated_ini is not None:
                            print(f"Updated {updated_ini.name} with offset {offset}")
                    else:
                        print("Spreadsheet match found but no numeric offset was available.")

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
        if total_songs > 0:
            print(f"Success rate: {(downloaded/total_songs*100):.1f}%")
        else:
            print("Success rate: N/A")
        print("=" * 70)


if __name__ == "__main__":
    main()
	
