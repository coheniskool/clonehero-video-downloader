# dedupe_report.py
# New standalone entry point (per SPEC-duplicate-detection.md): scans the
# library, groups song folders that are the same underlying song, confirms
# each candidate group via audio fingerprinting, scores each folder, moves
# everything except the highest-scoring "keeper" into _duplicates_review,
# and flags borrow-candidates. Never deletes anything.
#
# A real census (2026-07-14, Task 10) found 336 candidate duplicate groups /
# 844 folders (~16.5% of the 5,130-song library) via a cheap exact-key pass
# after stripping bracket-suffix noise like "[dup253]" -- common enough to
# be worth this feature's scope, not a rare edge case.

import importlib.util
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path

from clonehero_video_offset import find_song_audio

_REPO_ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('ch_video_script_for_dedupe', _REPO_ROOT / 'CH-VideoScript.py')
_ch_video_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ch_video_script)
parse_folder_name = _ch_video_script.parse_folder_name
normalize_lookup_value = _ch_video_script.normalize_lookup_value

#pyacoustid wraps fpcalc for generation AND provides compare_fingerprints()
#for proper Chromaprint decode + Hamming-distance bit-pattern comparison --
#not something worth hand-rolling. Neither pyacoustid nor the fpcalc binary
#are installed in this dev environment; guarded the same way OFFSET_SUPPORT
#guards audio_offset_finder, so this module stays importable/testable
#(mocked) regardless.
try:
    import acoustid
except ImportError as exc:
    acoustid = None
    print(f"Audio fingerprinting disabled (missing dependency: {exc}).")
    print("Run 'pip install pyacoustid' and ensure fpcalc (official AcoustID/Chromaprint release) is on PATH to enable it.")


#Real library pattern (confirmed 2026-07-14 census): a duplicate copy is
#often annotated with a "[dup2]"/"[dup253]"-style suffix. Neither
#parse_folder_name() nor strip_title_noise() strips this (they only handle
#trailing parenthetical/pedal noise), so an exact-key or fuzzy match without
#this step would miss real cases like "Weezer - My Name Is Jonas [dup3]".
_DUP_SUFFIX_RE = re.compile(r'\s*[\[\(]dup\d*[\]\)]\s*$', re.IGNORECASE)
_TRAILING_BRACKET_RE = re.compile(r'\s*\[[^\]]*\]\s*$')

#A version tag changes the underlying audio -- a live recording is not a
#duplicate of the studio original, even when title/artist match exactly.
#Two folders are only ever candidates for grouping when their version tags
#(or lack thereof) match.
_VERSION_TAG_RE = re.compile(
    r'\(\s*(live|acoustic|remix|cover|demo|instrumental|unplugged|remaster(?:ed)?|extended|radio edit)\b[^)]*\)',
    re.IGNORECASE,
)

ARTIST_MATCH_THRESHOLD = 90
TITLE_MATCH_THRESHOLD = 85


def _clean_folder_name(name):
    name = _DUP_SUFFIX_RE.sub('', name)
    name = _TRAILING_BRACKET_RE.sub('', name)
    return name


def _version_tag(title):
    match = _VERSION_TAG_RE.search(title)
    return match.group(1).lower() if match else None


def group_candidates(song_folders):
    """Fuzzy-group song folders that are likely the same underlying song.

    Produces CANDIDATE groups only -- confirm_group() (audio fingerprinting)
    narrows each candidate group to fingerprint-confirmed duplicates before
    anything gets scored or moved. Two folders are NEVER grouped if either
    has a version tag (Live/Acoustic/Remix/...) the other lacks, even when
    their base artist/title fuzzy-match closely.
    """
    parsed = []
    for folder in song_folders:
        cleaned_name = _clean_folder_name(folder.name)
        #version tag must be read from the name BEFORE parse_folder_name()'s
        #internal strip_title_noise() call -- that function silently removes
        #"(Live)"/"(Acoustic)"/"(Remix)" as YouTube-search noise, which would
        #make the tag invisible to this check if read from its output instead
        version_tag = _version_tag(cleaned_name)
        artist, title = parse_folder_name(cleaned_name)
        parsed.append({
            'folder': folder,
            'artist_norm': normalize_lookup_value(artist),
            'title_norm': normalize_lookup_value(title),
            'version_tag': version_tag,
        })

    groups = []
    used = set()
    for i, a in enumerate(parsed):
        if i in used:
            continue
        group = [a['folder']]
        for j in range(i + 1, len(parsed)):
            if j in used:
                continue
            b = parsed[j]
            if a['version_tag'] != b['version_tag']:
                continue
            artist_score = SequenceMatcher(None, a['artist_norm'], b['artist_norm']).ratio() * 100
            title_score = SequenceMatcher(None, a['title_norm'], b['title_norm']).ratio() * 100
            if artist_score >= ARTIST_MATCH_THRESHOLD and title_score >= TITLE_MATCH_THRESHOLD:
                group.append(b['folder'])
                used.add(j)
        if len(group) > 1:
            used.add(i)
            groups.append(group)

    return groups


#compare_fingerprints() returns a [0,1] similarity score; 0.95 requires a
#near-exact match (same recording, allowing for minor encode differences)
#without being so strict that ordinary lossy-encoding variance between two
#copies of the identical source audio would fail to match.
FINGERPRINT_MATCH_THRESHOLD = 0.95


def confirm_group(candidate_group):
    """Narrow a fuzzy-matched candidate group to fingerprint-confirmed duplicates.

    Fingerprints each folder's reference audio (find_song_audio) via
    pyacoustid/fpcalc and keeps only folders whose fingerprint actually
    matches the group's first successfully-fingerprinted folder. This is
    what catches cases fuzzy title matching alone can't: two folders with
    the same (or near-identical) title/artist that are nonetheless
    different underlying recordings.

    Returns a list of confirmed folders, or [] if fewer than two folders in
    the group are confirmed to match each other (nothing to dedupe), if
    fingerprinting is unavailable, or if any fingerprint call fails --
    never raises.
    """
    if acoustid is None:
        return []

    fingerprints = []
    for folder in candidate_group:
        audio_path = find_song_audio(folder)
        if audio_path is None:
            continue
        try:
            _duration, fingerprint = acoustid.fingerprint_file(str(audio_path))
        except Exception as e:
            logging.error(f"Fingerprint error {folder}: {e}")
            continue
        fingerprints.append((folder, fingerprint))

    if len(fingerprints) < 2:
        return []

    reference_folder, reference_fp = fingerprints[0]
    confirmed = [reference_folder]
    for folder, fp in fingerprints[1:]:
        try:
            similarity = acoustid.compare_fingerprints(reference_fp, fp)
        except Exception as e:
            logging.error(f"Fingerprint comparison error {folder}: {e}")
            continue
        if similarity >= FINGERPRINT_MATCH_THRESHOLD:
            confirmed.append(folder)

    return confirmed if len(confirmed) > 1 else []
