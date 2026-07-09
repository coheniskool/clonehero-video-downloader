#import youtube-dl
from __future__ import unicode_literals
import yt_dlp

import os
import re
from difflib import SequenceMatcher

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

def strip_title_noise(title: str) -> str:
    """Strip trailing noise patterns from song titles."""
    if not title:
        return title
    
    cleaned = title
    for pattern in (_TRAILING_DASH_NOISE_RE, _TRAILING_PAREN_NOISE_RE):
        candidate = pattern.sub("", cleaned).strip()
        if candidate:
            cleaned = candidate
    
    return cleaned

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

while True:
    threshold_input = input("Enter minimum confidence to auto-download without verification (0-100, or press Enter for 70): ").strip()
    if threshold_input == "":
        confidence_threshold = 70
        break
    try:
        confidence_threshold = int(threshold_input)
        if 0 <= confidence_threshold <= 100:
            break
        else:
            print("Please enter a number between 0 and 100.")
    except ValueError:
        print("Please enter a valid number.")

print(f"\nVideos with confidence >= {confidence_threshold} will download automatically.")
print(f"Videos with confidence < {confidence_threshold} will require your confirmation.")
print()
print("=" * 70)
print()

# Stats tracking
total_songs = 0
downloaded = 0
skipped = 0

try:
	for file in os.listdir():
		# Skip if not a directory
		if not os.path.isdir(file):
			continue
		
		total_songs += 1
		
		# Parse folder name to extract artist and title
		artist, title = parse_folder_name(file)
		
		# Build search query - prefer "Artist Song Official Music Video" format
		if artist and title:
			query = f"{artist} {title} official music video"
		elif title:
			query = f"{title} official music video"
		else:
			print(f"Skipping folder (couldn't parse name): {file}")
			skipped += 1
			continue
		
		print(f"Searching YouTube for: {query}")
		
		# Use yt-dlp's built-in YouTube search to get top 3 results
		search_query = f"ytsearch3:{query}"
		
		# Extract video info to get the actual URLs
		ydl_search_opts = {
			'quiet': True,
			'no_warnings': True,
			'extract_flat': True,  # Don't download, just get metadata
		}
		
		candidates = []
		try:
			with yt_dlp.YoutubeDL(ydl_search_opts) as ydl:
				info = ydl.extract_info(search_query, download=False)
				if info and 'entries' in info:
					for entry in info['entries']:
						if entry:
							video_id = entry['id']
							video_url = f"https://www.youtube.com/watch?v={video_id}"
							video_title = entry.get('title', 'Unknown')
							
							# Calculate confidence score
							confidence, reason = calculate_confidence(video_title, artist, title)
							
							candidates.append({
								'url': video_url,
								'title': video_title,
								'confidence': confidence,
								'reason': reason
							})
		except Exception as e:
			print(f"  Search error: {e}")
		
		if not candidates:
			print(f"No music video found for: {file}")
			skipped += 1
			continue
		
		# Sort by confidence (highest first)
		candidates.sort(key=lambda x: x['confidence'], reverse=True)
		best_match = candidates[0]
		
		# Show the best match
		print(f"  Best match: {best_match['title']}")
		print(f"  Confidence: {best_match['confidence']}/100 ({best_match['reason']})")
		print(f"  URL: {best_match['url']}")
		
		# Check if verification is needed
		if best_match['confidence'] < confidence_threshold:
			print()
			print(f"  ⚠️  Confidence below threshold ({best_match['confidence']} < {confidence_threshold})")
			print(f"  Song: {artist} - {title}" if artist else f"  Song: {title}")
			print()
			
			# Show all candidates
			print("  Top 3 matches found:")
			for i, cand in enumerate(candidates, 1):
				print(f"    {i}. [{cand['confidence']}%] {cand['title']}")
			print()
			
			while True:
				user_choice = input("  Download this video? (y=yes, n=skip, 1-3=pick different result, url=enter custom URL): ").strip().lower()
				
				if user_choice == 'y':
					url = best_match['url']
					break
				elif user_choice == 'n':
					print(f"  Skipping: {file}")
					url = None
					skipped += 1
					break
				elif user_choice in ['1', '2', '3']:
					idx = int(user_choice) - 1
					if idx < len(candidates):
						url = candidates[idx]['url']
						print(f"  Using: {candidates[idx]['title']}")
						break
					else:
						print("  Invalid choice, please try again.")
				elif user_choice == 'url':
					custom_url = input("  Enter YouTube URL: ").strip()
					if 'youtube.com/watch' in custom_url or 'youtu.be/' in custom_url:
						url = custom_url
						print(f"  Using custom URL: {custom_url}")
						break
					else:
						print("  Invalid YouTube URL, please try again.")
				else:
					print("  Invalid choice, please enter y, n, 1-3, or url.")
			
			if url is None:
				continue
			print()
		else:
			# Auto-download high confidence matches
			url = best_match['url']
			print(f"  ✓ High confidence - auto-downloading")
			print()
		
		#changes the download folder
		currentSongFileFolder = os.path.join(homeFolder, file)
		try:
			os.chdir(currentSongFileFolder)
		except Exception as e:
			print(f"  ERROR: Cannot access folder {file}: {e}")
			skipped += 1
			continue

		#downloads the song in the correct folder
		#IN THE FUTURE ADD 'format': 'bestaudio/best' TO ydl_opts (so that quality can be improved)
		ydl_opts = {'outtmpl': 'video.mp4',
					'nooverwrites': 0,
					'noplaylist': 1}
		try:
			with yt_dlp.YoutubeDL(ydl_opts) as ydl:
				ydl.download([url])
			downloaded += 1
			print(f"Downloaded video for: {file}\n")
		except Exception as e:
			print(f"  ERROR: Download failed for {file}: {e}")
			skipped += 1
		
		# Return to home folder for next iteration
		os.chdir(homeFolder)

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
	
