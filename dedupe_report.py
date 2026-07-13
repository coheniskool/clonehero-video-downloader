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
import json
import logging
import re
import shutil
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


#The 13 real diff_* fields confirmed from the Chorus schema (Task 0) --
#Clone Hero's own song.ini uses the same key names for its per-instrument
#difficulty ratings, -1 meaning "not charted".
DIFF_KEYS = (
    'diff_band', 'diff_guitar', 'diff_guitar_coop', 'diff_rhythm', 'diff_bass',
    'diff_drums', 'diff_drums_real', 'diff_keys', 'diff_guitarghl',
    'diff_guitar_coop_ghl', 'diff_rhythm_ghl', 'diff_bassghl', 'diff_vocals',
)
METADATA_KEYS = ('year', 'genre', 'charter', 'album')


def score_folder(song_dir, video_meta, song_ini_fields, chorus_data):
    """Score a folder's quality/completeness signals for keeper selection.

    Returns (score, breakdown) -- breakdown is a dict of {signal_name:
    points} so the report can show *why* a folder won, not just the final
    number. Weighted heavily toward instrument/chart completeness (the
    actual playable content) over video/offset/metadata/Chorus, which are
    smaller supplementary signals. See SPEC-duplicate-detection.md's Code
    Style section for the full rationale behind these specific weights.
    """
    breakdown = {}
    breakdown['has_video'] = 10 if video_meta.get('video_status') == 'present' else 0
    breakdown['offset_confidence'] = min(video_meta.get('offset_confidence', 0), 10)
    breakdown['instrument_count'] = sum(
        1 for key in DIFF_KEYS if song_ini_fields.get(key, -1) != -1
    ) * 5
    breakdown['metadata_completeness'] = sum(
        1 for key in METADATA_KEYS if song_ini_fields.get(key)
    ) * 2
    #re-scoped from the original (nonexistent) "upvotes" idea (Task 0): a
    #small bonus when Chorus's own record has no known issues -- a quality
    #flag, not a popularity/rating measure, since no rating field exists
    breakdown['chorus_signal'] = (
        5 if chorus_data and not chorus_data.get('folderIssues') and not chorus_data.get('metadataIssues') else 0
    )
    return sum(breakdown.values()), breakdown


def is_keeper_eligible(video_meta):
    """True only if chart_rename_status is exactly 'confirmed_ok'.

    Absence (not yet scanned by SPEC-chart-rename.md) is treated identically
    to 'needs_review' -- an unscanned folder's actual chart/audio content is
    just as unconfirmed as a flagged one, and picking either as a keeper
    would permanently promote a potentially wrong chart under the right
    folder name.
    """
    return video_meta.get('chart_rename_status') == 'confirmed_ok'


def select_keeper(group, scores, eligibility):
    """Pick the highest-scoring keeper-eligible folder in a group.

    Hard precondition, not just documented intent: never returns a folder
    that isn't keeper-eligible, even if it scored highest. Returns None if
    no folder in the group is eligible -- the caller must skip the whole
    group and flag it for manual attention rather than auto-resolving it.
    """
    eligible = [folder for folder in group if eligibility.get(folder)]
    if not eligible:
        return None
    return max(eligible, key=lambda folder: scores[folder])


DUPLICATES_REVIEW_MANIFEST_FILENAME = '_duplicates_review_manifest.jsonl'


def _dest_is_same_volume(source, dest_parent):
    import os
    try:
        return os.stat(source).st_dev == os.stat(dest_parent).st_dev
    except OSError:
        return False


def _folder_size_and_count(folder):
    total_size = 0
    count = 0
    for p in Path(folder).rglob('*'):
        if p.is_file():
            total_size += p.stat().st_size
            count += 1
    return total_size, count


def _append_duplicates_review_manifest(home_folder, source, dest, reason, score, cross_volume, verification):
    manifest_path = Path(home_folder) / DUPLICATES_REVIEW_MANIFEST_FILENAME
    entry = {
        'source': str(source),
        'destination': str(dest),
        'score': score,
        'reason': reason,
        'cross_volume': cross_volume,
        'verification': verification,
    }
    with manifest_path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(entry) + '\n')


def move_to_duplicates_review(song_dir, home_folder, reason, score, dry_run=False):
    """Relocate a losing duplicate folder intact into _duplicates_review/.

    Mirrors clonehero_video_offset.py's move_to_needs_review() exactly (same
    same-volume/cross-volume-aware logic, same "[dupN]" collision-naming
    scheme) for cross-feature consistency -- this is a proven mechanism, not
    a new design. The one difference: the manifest entry here includes the
    folder's score, since that's meaningful context a chart-rename
    relocation doesn't have.

    Resumability is implicit: once a folder is moved out of the library
    root, it simply won't appear in the next run's folder scan, so
    group_candidates() naturally stops finding it as a duplicate -- no
    separate state file is needed.

    dry_run=True computes and returns None without moving, relocating, or
    logging anything.
    """
    if dry_run:
        return None

    song_dir = Path(song_dir)
    home_folder = Path(home_folder)
    review_root = home_folder / '_duplicates_review'
    review_root.mkdir(parents=True, exist_ok=True)

    dest = review_root / song_dir.name
    if dest.exists():
        suffix = 1
        while (review_root / f'{song_dir.name} [dup{suffix}]').exists():
            suffix += 1
        dest = review_root / f'{song_dir.name} [dup{suffix}]'

    cross_volume = not _dest_is_same_volume(song_dir, review_root)

    if not cross_volume:
        shutil.move(str(song_dir), str(dest))
        _append_duplicates_review_manifest(home_folder, song_dir, dest, reason, score, cross_volume, 'not_applicable')
        return dest

    source_size, source_count = _folder_size_and_count(song_dir)
    shutil.copytree(str(song_dir), str(dest))
    dest_size, dest_count = _folder_size_and_count(dest)

    if dest_size != source_size or dest_count != source_count:
        _append_duplicates_review_manifest(home_folder, song_dir, dest, reason, score, cross_volume, 'failed')
        raise RuntimeError(
            f'cross-volume copy verification failed for {song_dir.name}: '
            f'source had {source_count} files/{source_size} bytes, '
            f'destination has {dest_count} files/{dest_size} bytes -- source left untouched, '
            f'incomplete copy left at {dest}'
        )

    shutil.rmtree(str(song_dir))
    _append_duplicates_review_manifest(home_folder, song_dir, dest, reason, score, cross_volume, 'ok')
    return dest


def flag_borrow_candidates(keeper_ini_fields, keeper_video_meta, loser_ini_fields, loser_video_meta):
    """Report-only: flag things a loser has that the keeper lacks.

    Never acts on these -- purely informational so the user can decide
    whether a manual merge is worth doing before deleting the loser (e.g. a
    Pro Drums track, a set difficulty rating, a background video the keeper
    doesn't have). Never writes to any chart/song.ini/audio file.
    """
    flags = []
    for key in DIFF_KEYS:
        keeper_has = keeper_ini_fields.get(key, -1) != -1
        loser_has = loser_ini_fields.get(key, -1) != -1
        if loser_has and not keeper_has:
            flags.append(f'{key} (loser has it, keeper does not)')

    if loser_video_meta.get('video_status') == 'present' and keeper_video_meta.get('video_status') != 'present':
        flags.append('video background (loser has it, keeper does not)')

    return flags
