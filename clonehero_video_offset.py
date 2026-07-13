# clonehero_video_offset.py
# pip install audio-offset-finder numpy
# NOTE: numpy must land in the >=2,<=2.4 window on this environment -- numpy 1.26.x
# breaks scipy's C extensions on Python 3.14, and numpy 2.5+ breaks numba (a librosa
# dependency, which audio-offset-finder itself uses internally for MFCC computation).

import json
import os
import re
import shutil
import subprocess
import tempfile
from difflib import SequenceMatcher
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
from audio_offset_finder.audio_offset_finder import find_offset_between_files

handler = RotatingFileHandler('clonehero_offset.log', maxBytes=1_000_000, backupCount=5)
logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s - %(levelname)s - %(message)s')

#audio-offset-finder's "standard score" is a z-score of the correlation peak (standard
#deviations above the mean of the correlation curve) -- a very different scale from the
#old DTW confidence_ratio this replaces. 0.5 was the default confirmed during /spec
#review, before this backend was empirically tested; a smoke test against a clean
#synthetic signal (Task 5 commit) scored ~8.8, so 0.5 may be far too permissive to
#ever flag a genuinely weak match. Flagged for recalibration once Task 12's
#real-library validation provides real-world scores to tune against -- not changed
#here without asking, per the spec's "ask first" boundary on this threshold.
MIN_STANDARD_SCORE = 0.5

#Clone Hero's own convention for the full mixed track. Multitrack charts also
#ship isolated stems (drums.ogg, crowd.ogg, vocals.ogg, ...) that must NOT be
#used as the alignment reference -- their onset pattern doesn't correspond to
#the video's full mix at all.
FULL_MIX_NAMES = ('song.ogg', 'song.opus', 'song.mp3', 'song.wav')
#Only Clone Hero's officially recognized background-video filenames.
VIDEO_NAMES = ('video.mp4', 'video.avi', 'video.webm', 'video.ogv')


def find_song_audio(song_dir):
    #filename is always "song*" regardless of numeric suffix -- some libraries use
    #"song.ogg", others "song_1877.ogg" from a different chart source. Glob instead
    #of matching FULL_MIX_NAMES exactly so ID-suffixed folders aren't silently skipped.
    for ext in ('.ogg', '.opus', '.mp3', '.wav'):
        matches = sorted(song_dir.glob('song*' + ext))
        if matches:
            return matches[0]
    #No dedicated full-mix file -- only safe to use a stem if it's the only track present.
    audio_files = [f for f in song_dir.glob('*') if f.suffix.lower() in {'.ogg', '.mp3', '.wav', '.opus'}]
    return audio_files[0] if len(audio_files) == 1 else None


def find_song_ini(song_dir):
    #also inconsistently named across the library ("song.ini" vs "song_2400.ini") -- there
    #is always exactly one *.ini file per song folder regardless of chart source, so match
    #on that, preferring the literal "song.ini" name when more than one .ini exists.
    ini_files = sorted(song_dir.glob('*.ini'))
    if not ini_files:
        return None
    return next((p for p in ini_files if p.name.lower() == 'song.ini'), ini_files[0])


def find_video_file(song_dir):
    for name in VIDEO_NAMES:
        candidate = song_dir / name
        if candidate.exists():
            return candidate
    return None


#Clone Hero requires these exact literal filenames -- confirmed against the
#official wiki (Adding Custom Songs / song.ini Guide). A folder whose .ini or
#chart file is numeric-ID-suffixed (song_2400.ini, notes_454.chart) instead of
#literal can't be loaded by the game at all, regardless of file content being
#otherwise correct.
CANONICAL_CHART_NAMES = {'song.ini', 'notes.chart', 'notes.mid'}


def scan_song_folder_chart_names(song_dir):
    """Detect (but do not verify or rename) ID-suffixed chart filenames.

    Returns {'status': ..., 'detail': ...} where status is one of:
    'ok' (song.ini and a notes.chart/.mid are both present with literal
    names), 'id_suffixed' (the .ini and/or chart file is numeric-ID-suffixed
    -- detail lists which), 'no_ini' (no *.ini file at all), 'no_chart_file'
    (a literal or ID-suffixed .ini exists but no notes.chart/.mid does),
    'ambiguous' (more than one .ini, or more than one chart/.mid candidate,
    exists in the same folder -- e.g. a leftover suffixed file alongside an
    already-correct literal one. Never silently pick one and ignore the
    other; that's exactly the collision case Task 4's rename guard must
    catch, not something detection should hide).

    This is detection only -- verifying that an ID-suffixed file's content
    actually matches the folder's stated song (Tasks 2/3), and the rename/
    collision/relocation logic (Task 4), are separate steps layered on top.
    """
    ini_files = sorted(song_dir.glob('*.ini'))
    if not ini_files:
        return {'status': 'no_ini', 'detail': ''}
    if len(ini_files) > 1:
        return {'status': 'ambiguous', 'detail': ', '.join(p.name for p in ini_files)}
    ini_file = ini_files[0]

    chart_candidates = (
        sorted(song_dir.glob('notes.chart')) + sorted(song_dir.glob('notes_*.chart'))
        + sorted(song_dir.glob('notes.mid')) + sorted(song_dir.glob('notes_*.mid'))
    )
    if len(chart_candidates) > 1:
        return {'status': 'ambiguous', 'detail': ', '.join(p.name for p in chart_candidates)}
    chart_file = chart_candidates[0] if chart_candidates else None

    if chart_file is None:
        return {'status': 'no_chart_file', 'detail': ini_file.name}

    id_suffixed = [
        p.name for p in (ini_file, chart_file)
        if p.name.lower() not in CANONICAL_CHART_NAMES
    ]
    if id_suffixed:
        return {'status': 'id_suffixed', 'detail': ', '.join(id_suffixed)}

    return {'status': 'ok', 'detail': f'{ini_file.name}, {chart_file.name}'}


#Duplicated from CH-VideoScript.py's normalize_lookup_value() rather than
#imported, to avoid a circular import (CH-VideoScript.py imports FROM this
#module). Keep in sync if that logic ever changes.
def _normalize_for_match(value):
    if value is None:
        return ''
    return re.sub(r'[^a-z0-9]+', ' ', str(value).strip().lower()).strip()


#Both Name AND Artist must independently clear this -- set higher than the
#project's existing YouTube-match "high confidence" band (70-89) because a
#wrong rename is a less-reversible mistake than downloading a wrong video.
CHART_NAME_MATCH_THRESHOLD = 85

_CHART_NAME_RE = re.compile(r'(?im)^\s*name\s*=\s*"([^"]*)"')
_CHART_ARTIST_RE = re.compile(r'(?im)^\s*artist\s*=\s*"([^"]*)"')


def read_chart_song_fields(chart_path):
    """Read the [Song] section's Name/Artist text fields from a .chart file.

    Plain-text regex, not a full .chart parser -- matches this project's
    existing byte-preserving-regex philosophy. Returns {} if the file can't
    be read or neither field is present.
    """
    try:
        text = chart_path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return {}
    fields = {}
    name_match = _CHART_NAME_RE.search(text)
    if name_match:
        fields['name'] = name_match.group(1)
    artist_match = _CHART_ARTIST_RE.search(text)
    if artist_match:
        fields['artist'] = artist_match.group(1)
    return fields


#Standard MIDI files carry no equivalent human-readable song-name text chunk
#Clone Hero charts reliably populate, so .mid folders fall back to comparing
#the paired audio's real duration against song.ini's song_length (ms).
MID_DURATION_TOLERANCE_MS = 2000


def probe_audio_duration_ms(audio_path):
    """Return an audio file's duration in milliseconds via ffprobe, or None on failure."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(audio_path)],
            check=True, capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        duration = data.get('format', {}).get('duration')
        if duration is None:
            return None
        return round(float(duration) * 1000)
    except Exception as e:
        logging.error(f"ffprobe duration probe error {audio_path}: {e}")
        return None


def verify_chart_content_match(song_dir, ini_fields):
    """Fuzzy-verify a chart file's content against song.ini.

    Returns (matched, reason). For a .chart file: both Name and Artist must
    independently score >= CHART_NAME_MATCH_THRESHOLD (SequenceMatcher
    ratio*100) -- an OR check would wrongly pass the real Mr. Roboto case,
    where Artist matches ("Styx") but Name is a completely different song
    ("Rock & Roll Feeling"). For a .mid file (no embedded text metadata to
    compare), falls back to comparing the paired audio's real duration
    against song.ini's song_length, within MID_DURATION_TOLERANCE_MS.
    """
    chart_files = sorted(song_dir.glob('*.chart'))
    if chart_files:
        chart_fields = read_chart_song_fields(chart_files[0])
        if not chart_fields:
            return False, f'{chart_files[0].name}: no Name/Artist fields found'

        scores = {}
        for key in ('name', 'artist'):
            chart_value = _normalize_for_match(chart_fields.get(key))
            ini_value = _normalize_for_match(ini_fields.get(key))
            scores[key] = round(SequenceMatcher(None, chart_value, ini_value).ratio() * 100)

        failing = [key for key, score in scores.items() if score < CHART_NAME_MATCH_THRESHOLD]
        if failing:
            detail = ', '.join(f'{key} score {scores[key]}' for key in failing)
            return False, f'{chart_files[0].name}: {detail} below threshold {CHART_NAME_MATCH_THRESHOLD}'
        return True, ''

    mid_files = sorted(song_dir.glob('*.mid'))
    if not mid_files:
        return False, 'no .chart or .mid file found to verify against'

    song_length_raw = ini_fields.get('song_length')
    if not song_length_raw:
        return False, 'song.ini has no song_length to compare against'
    try:
        expected_ms = int(str(song_length_raw).strip())
    except ValueError:
        return False, f'song.ini song_length {song_length_raw!r} is not numeric'

    audio_path = find_song_audio(song_dir)
    if audio_path is None:
        return False, 'no audio file found to probe duration against'

    actual_ms = probe_audio_duration_ms(audio_path)
    if actual_ms is None:
        return False, f'{audio_path.name}: ffprobe could not determine duration'

    diff_ms = abs(actual_ms - expected_ms)
    if diff_ms > MID_DURATION_TOLERANCE_MS:
        return False, (
            f'{mid_files[0].name}: audio duration {actual_ms}ms differs from '
            f'song_length {expected_ms}ms by {diff_ms}ms, exceeds tolerance {MID_DURATION_TOLERANCE_MS}ms'
        )
    return True, ''


#Complete reserved stem-role set per the canonical chart-format reference
#(https://thenathannator.github.io/GuitarGame_ChartFormats/Chart-File-Formats/
#Supported-Audio-Files/, linked from the official Clone Hero wiki) -- an
#earlier draft of this check only had song/guitar/rhythm/bass/drums(_1-4)/
#vocals/keys/crowd, missing preview and the vocals_* family.
STEM_ROLES = (
    'preview', 'song', 'guitar', 'rhythm', 'bass', 'keys', 'crowd',
    'drums', 'drums_1', 'drums_2', 'drums_3', 'drums_4',
    'vocals', 'vocals_1', 'vocals_2',
    'vocals_explicit', 'vocals_explicit_1', 'vocals_explicit_2',
)
AUDIO_STEM_EXTENSIONS = ('.ogg', '.mp3', '.wav', '.opus')


def _match_stem_role(file_stem):
    """Return (role, is_id_suffixed) for a filename stem, or (None, None).

    Two passes so a filename like "vocals_1.ogg" is recognized as a literal
    match for the reserved role "vocals_1" (a real harmony-vocals stem) rather
    than mistakenly parsed as role "vocals" with numeric ID "1".
    """
    lowered = file_stem.lower()
    for role in STEM_ROLES:
        if lowered == role:
            return role, False
    for role in STEM_ROLES:
        prefix = role + '_'
        if lowered.startswith(prefix) and lowered[len(prefix):].isdigit():
            return role, True
    return None, None


def scan_song_folder_audio_stems(song_dir):
    """Classify each recognized audio-stem role's naming state in a folder.

    Returns {'status': ..., 'detail': ...}. Statuses: 'ok' (every present role
    has exactly one literally-named file, or no audio at all -- absence isn't
    this check's concern), 'rename_candidate' (one or more roles each have
    exactly one ID-suffixed candidate and nothing else -- safe to rename,
    weak verification since there's no embedded metadata to check against),
    'needs_review' (a role has multiple candidate files, literal+ID-suffixed
    both present for the same role, or unrecognized ambiguity -- never
    auto-picked; this is the real Kryptonite shape: four guitar candidates,
    two rhythm candidates, two conflicting drum-mixing conventions).

    A real 2026-07-14 census found 1,083 of 5,130 real library folders (~21%)
    missing a literal song.* file; 250 of those (~5% of the library) have
    multiple conflicting candidates -- this isn't a rare edge case.
    """
    by_role = {}
    for path in song_dir.iterdir():
        if not path.is_file() or path.suffix.lower() not in AUDIO_STEM_EXTENSIONS:
            continue
        role, is_id_suffixed = _match_stem_role(path.stem)
        if role is None:
            continue
        by_role.setdefault(role, []).append((path, is_id_suffixed))

    ambiguous_roles = {role: files for role, files in by_role.items() if len(files) > 1}
    if ambiguous_roles:
        detail = '; '.join(
            f'{role}: {", ".join(p.name for p, _ in files)}'
            for role, files in sorted(ambiguous_roles.items())
        )
        return {'status': 'needs_review', 'detail': detail}

    rename_candidates = {
        role: files[0][0] for role, files in by_role.items()
        if files[0][1]  # the sole candidate is ID-suffixed
    }
    if rename_candidates:
        detail = ', '.join(f'{role}: {path.name}' for role, path in sorted(rename_candidates.items()))
        return {'status': 'rename_candidate', 'detail': detail}

    return {'status': 'ok', 'detail': ''}


#Album art is expected in the track-selection screen but never blocks
#loading a song the way a missing chart/audio file does -- confirmed via
#the official wiki ("Other Custom Content"). Zero candidates is a valid,
#non-blocking outcome, unlike scan_song_folder_audio_stems().
ALBUM_ART_EXTENSIONS = ('.png', '.jpg', '.jpeg')


def scan_song_folder_album_art(song_dir):
    """Classify album-art naming state: literal 'album.{png,jpg,jpeg}'.

    Returns {'status': ..., 'detail': ...}. Statuses: 'ok' (a literal match
    exists, or none at all -- album art isn't hard-required), 'rename_candidate'
    (exactly one ID-suffixed candidate and nothing else -- safe to rename, no
    embedded metadata to verify against), 'needs_review' (multiple candidates,
    or a literal name coexisting with an ID-suffixed one -- never auto-picked).

    Real folders (Kryptonite: album_827.png, Mr. Roboto: album_822.jpg, You
    Only Live Once: album_525.jpg) show this is the same generating bug that
    produces ID-suffixed song.ini/notes.chart/notes.mid, just hitting a file
    type this spec originally missed.
    """
    candidates = []
    for ext in ALBUM_ART_EXTENSIONS:
        for path in song_dir.glob('album*' + ext):
            stem = path.stem.lower()
            if stem == 'album' or (stem.startswith('album_') and stem[len('album_'):].isdigit()):
                candidates.append(path)

    if len(candidates) > 1:
        detail = ', '.join(p.name for p in sorted(candidates, key=lambda p: p.name))
        return {'status': 'needs_review', 'detail': detail}

    if not candidates:
        return {'status': 'ok', 'detail': ''}

    sole = candidates[0]
    if sole.stem.lower() == 'album':
        return {'status': 'ok', 'detail': sole.name}
    return {'status': 'rename_candidate', 'detail': sole.name}


def is_sng_packaged(song_dir):
    """True if the folder contains a .sng single-file chart container.

    Clone Hero's newer .sng format bundles and replaces the loose-file
    structure entirely -- "cannot be edited manually" per the official wiki.
    Callers must skip all rename/verification checks for such a folder;
    there's nothing loose to verify or rename.
    """
    return any(song_dir.glob('*.sng'))


def read_song_ini_fields(ini_path, keys):
    """Read specific top-level fields from a song.ini file, read-only.

    Regex-based (not configparser), consistent with this project's existing
    ini-handling philosophy -- but this is read-only, so no formatting-
    preservation concerns apply the way they do for patch_song_ini().
    """
    try:
        text = ini_path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return {}
    fields = {}
    for key in keys:
        match = re.search(rf'(?im)^[ \t]*{re.escape(key)}[ \t]*=[ \t]*(.*?)[ \t]*$', text)
        if match:
            fields[key.lower()] = match.group(1)
    return fields


def process_chart_folder_names(song_dir, dry_run=False):
    """Verify and rename ID-suffixed song.ini/notes.chart/notes.mid, with a collision guard.

    Returns {'status': ..., 'detail': ...}. Statuses: 'confirmed_ok' (already
    literally named, or safely renamed after content verification passed),
    'needs_review' (content couldn't be confirmed, a rename target already
    exists, or there's nothing to verify against), 'skipped_sng'
    (is_sng_packaged() -- left completely untouched).

    dry_run=True computes and returns the same status/detail without
    renaming anything -- the reported outcome describes what WOULD happen.

    Does not check audio-stem or album-art naming, and does not relocate
    needs_review folders -- callers combine this with
    scan_song_folder_audio_stems()/scan_song_folder_album_art() and
    move_to_needs_review() to decide and act on the folder's overall outcome.
    """
    if is_sng_packaged(song_dir):
        return {'status': 'skipped_sng', 'detail': ''}

    detection = scan_song_folder_chart_names(song_dir)
    if detection['status'] == 'ok':
        return {'status': 'confirmed_ok', 'detail': detection['detail']}
    if detection['status'] in ('no_ini', 'no_chart_file', 'ambiguous'):
        return {'status': 'needs_review', 'detail': f"{detection['status']}: {detection['detail']}"}

    # detection['status'] == 'id_suffixed' -- verify content before touching anything
    ini_files = sorted(song_dir.glob('*.ini'))
    ini_file = next((p for p in ini_files if p.name.lower() == 'song.ini'), ini_files[0])
    ini_fields = read_song_ini_fields(ini_file, ('name', 'artist', 'song_length'))

    matched, reason = verify_chart_content_match(song_dir, ini_fields)
    if not matched:
        return {'status': 'needs_review', 'detail': reason}

    chart_files = sorted(song_dir.glob('*.chart'))
    mid_files = sorted(song_dir.glob('*.mid'))
    chart_file = chart_files[0] if chart_files else (mid_files[0] if mid_files else None)
    if chart_file is None:
        return {'status': 'needs_review', 'detail': 'no .chart or .mid file found to rename'}
    target_chart_name = 'notes.chart' if chart_file.suffix.lower() == '.chart' else 'notes.mid'
    target_chart = song_dir / target_chart_name

    #collision guard: never overwrite a file that already exists at the target
    #name -- can happen if a prior partial run or manual edit left both present
    target_ini = song_dir / 'song.ini'
    if ini_file.name.lower() != 'song.ini' and target_ini.exists():
        return {'status': 'needs_review', 'detail': f'{ini_file.name}: song.ini already exists'}
    if chart_file.name.lower() != target_chart_name and target_chart.exists():
        return {'status': 'needs_review', 'detail': f'{chart_file.name}: {target_chart_name} already exists'}

    renamed = []
    if ini_file.name.lower() != 'song.ini':
        if not dry_run:
            ini_file.rename(target_ini)
        renamed.append(f'{ini_file.name} -> song.ini')
    if chart_file.name.lower() != target_chart_name:
        if not dry_run:
            chart_file.rename(target_chart)
        renamed.append(f'{chart_file.name} -> {target_chart_name}')

    detail = '; '.join(renamed) if renamed else 'already correct'
    if dry_run and renamed:
        detail += ' (dry-run, not applied)'
    return {'status': 'confirmed_ok', 'detail': detail}


NEEDS_REVIEW_MANIFEST_FILENAME = '_needs_review_manifest.jsonl'


def _dest_is_same_volume(source, dest_parent):
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


def _append_needs_review_manifest(home_folder, source, dest, reason, cross_volume, verification):
    manifest_path = Path(home_folder) / NEEDS_REVIEW_MANIFEST_FILENAME
    entry = {
        'source': str(source),
        'destination': str(dest),
        'reason': reason,
        'cross_volume': cross_volume,
        'verification': verification,
    }
    with manifest_path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(entry) + '\n')


def move_to_needs_review(song_dir, home_folder, reason):
    """Relocate song_dir intact into _needs_review/ at home_folder's root.

    Same-volume moves use shutil.move() directly (atomic rename under the
    hood). Cross-volume moves copy to the destination first, verify total
    file count and byte size match the source, and only remove the source
    after that verification passes -- an interrupted cross-volume move must
    never leave the library in a state where the folder exists nowhere
    complete. Every move (either case) is appended to a JSONL manifest.
    Raises RuntimeError (source left untouched) if cross-volume verification
    fails.
    """
    song_dir = Path(song_dir)
    home_folder = Path(home_folder)
    review_root = home_folder / '_needs_review'
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
        _append_needs_review_manifest(home_folder, song_dir, dest, reason, cross_volume, 'not_applicable')
        return dest

    source_size, source_count = _folder_size_and_count(song_dir)
    shutil.copytree(str(song_dir), str(dest))
    dest_size, dest_count = _folder_size_and_count(dest)

    if dest_size != source_size or dest_count != source_count:
        _append_needs_review_manifest(home_folder, song_dir, dest, reason, cross_volume, 'failed')
        raise RuntimeError(
            f'cross-volume copy verification failed for {song_dir.name}: '
            f'source had {source_count} files/{source_size} bytes, '
            f'destination has {dest_count} files/{dest_size} bytes -- source left untouched, '
            f'incomplete copy left at {dest}'
        )

    shutil.rmtree(str(song_dir))
    _append_needs_review_manifest(home_folder, song_dir, dest, reason, cross_volume, 'ok')
    return dest


#Same file CH-VideoScript.py's VIDEO_METADATA_FILENAME points at -- duplicated
#as a literal (not imported) to avoid a circular import; keep in sync.
CHART_RENAME_METADATA_FILENAME = 'video_meta.json'


def load_chart_rename_status(song_dir):
    """Return the persisted chart_rename_status, or None if not yet scanned.

    Absence (None) is a distinct third state from 'confirmed_ok'/'needs_review'
    -- callers (notably SPEC-duplicate-detection.md's keeper-scoring) must
    treat it identically to 'needs_review', never as "assumed clean".
    """
    metadata_path = Path(song_dir) / CHART_RENAME_METADATA_FILENAME
    if not metadata_path.exists():
        return None
    try:
        with metadata_path.open('r', encoding='utf-8') as handle:
            data = json.load(handle)
        return data.get('chart_rename_status')
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def save_chart_rename_status(song_dir, status, detail=''):
    """Persist chart_rename_status into video_meta.json, merging with existing fields.

    Merges rather than overwrites so this never clobbers video-match/offset
    fields the offset feature already wrote for the same folder.
    """
    metadata_path = Path(song_dir) / CHART_RENAME_METADATA_FILENAME
    metadata = {}
    if metadata_path.exists():
        try:
            with metadata_path.open('r', encoding='utf-8') as handle:
                metadata = json.load(handle)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
    metadata['chart_rename_status'] = status
    metadata['chart_rename_detail'] = detail
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')


def process_song_folder_for_chart_rename(song_dir, home_folder, dry_run=False):
    """Full per-folder chart-rename pass: names + audio-stems + album-art.

    Returns {'status': ..., 'detail': ...}. Statuses: 'confirmed_ok' (the
    ini/chart/mid check, audio-stem check, AND album-art check all pass),
    'needs_review' (any check fails -- the folder is relocated intact to
    _needs_review/ via move_to_needs_review(), unless dry_run), 'skipped_sng',
    'skipped_settled' (chart_rename_status was already 'confirmed_ok' on a
    prior run -- resumability).

    dry_run=True computes the same outcome without renaming, relocating, or
    persisting anything.
    """
    song_dir = Path(song_dir)

    if is_sng_packaged(song_dir):
        return {'status': 'skipped_sng', 'detail': ''}

    if load_chart_rename_status(song_dir) == 'confirmed_ok':
        return {'status': 'skipped_settled', 'detail': 'already confirmed_ok'}

    names_result = process_chart_folder_names(song_dir, dry_run=dry_run)
    audio_result = scan_song_folder_audio_stems(song_dir)
    album_art_result = scan_song_folder_album_art(song_dir)

    failures = [
        r['detail'] for r in (names_result, audio_result, album_art_result)
        if r['status'] not in ('confirmed_ok', 'ok')
    ]

    if failures:
        detail = '; '.join(failures)
        if not dry_run:
            move_to_needs_review(song_dir, home_folder, detail)
            #status intentionally not persisted here -- the folder no longer
            #exists at song_dir once relocated, and the manifest already
            #records the relocation and its reason
        return {'status': 'needs_review', 'detail': detail}

    if not dry_run:
        save_chart_rename_status(song_dir, 'confirmed_ok', names_result['detail'])
    return {'status': 'confirmed_ok', 'detail': names_result['detail']}


def probe_frame_rate(video_path):
    #Variable Frame Rate (VFR) source video causes progressive, cumulative audio/video
    #desync that a single static video_start_time offset cannot fix -- it only corrects
    #the start point, not a drift that grows over the video's duration. r_frame_rate
    #(the stream's nominal/container rate) and avg_frame_rate (the actual average over
    #the whole stream) disagree exactly when the video is VFR; they match for CFR.
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=r_frame_rate,avg_frame_rate',
             '-of', 'json', str(video_path)],
            check=True, capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        streams = data.get('streams', [])
        if not streams:
            return False
        stream = streams[0]
        return stream.get('r_frame_rate', '0/0') != stream.get('avg_frame_rate', '0/0')
    except Exception as e:
        logging.error(f"ffprobe error {video_path}: {e}")
        return False


def probe_video_codec(video_path):
    #Returns the video stream's codec name (e.g. "h264", "vp8", "vp9"), or None if
    #ffprobe fails or no video stream is found. Used to catch WebM files encoded with
    #VP9 -- YouTube's default for "bestvideo[ext=webm]" on virtually all current
    #uploads -- which this Clone Hero build cannot decode at all (confirmed via a real
    #playtest: "Unsupported video codec 'VP9'", video never renders). Only VP8 is safe.
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name',
             '-of', 'json', str(video_path)],
            check=True, capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        streams = data.get('streams', [])
        if not streams:
            return None
        return streams[0].get('codec_name')
    except Exception as e:
        logging.error(f"ffprobe codec probe error {video_path}: {e}")
        return None


def reencode_to_cfr(video_path, fps=30):
    #Overwrites video_path in place with a constant-frame-rate re-encode, no backup kept
    #(confirmed decision -- keeps disk usage flat for a 5,000+ song library). Writes to a
    #temp file in the same directory first so a crash mid-encode can't leave a partial/
    #corrupt file at the real path.
    video_path = Path(video_path)
    fd, tmp_path = tempfile.mkstemp(dir=str(video_path.parent), suffix=video_path.suffix)
    os.close(fd)
    try:
        subprocess.run(
            ['ffmpeg', '-nostdin', '-i', str(video_path), '-r', str(fps), '-y', tmp_path],
            check=True, capture_output=True, stdin=subprocess.DEVNULL,
        )
        os.replace(tmp_path, str(video_path))
        return True
    except Exception as e:
        logging.error(f"CFR re-encode error {video_path}: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False


def extract_audio(video_path, out_wav):
    try:
        subprocess.run(['ffmpeg', '-nostdin', '-i', str(video_path), '-vn', '-ar', '16000', '-ac', '1', '-y', str(out_wav)],
                        check=True, capture_output=True, stdin=subprocess.DEVNULL)
        return True
    except Exception as e:
        logging.error(f"FFmpeg error {video_path}: {e}")
        return False

def compute_offset(song_path, vid_audio):
    try:
        result = find_offset_between_files(str(song_path), str(vid_audio))
        #find_offset_between_files' own docstring claims a positive time_offset means
        #"file2 starts after file1" -- empirically verified during implementation that
        #its actual behavior is the opposite (a controlled test: delaying file2's content
        #by a known +0.25s produced time_offset=-0.248, not +0.248). Negating it here
        #converts to Clone Hero's video_start_time convention: positive = skip ahead
        #into the video (it has an intro before the song starts), negative = delay the
        #video's appearance (the video is missing its intro).
        offset_ms = round(-result["time_offset"] * 1000)
        confidence_ratio = result["standard_score"]

        if confidence_ratio < MIN_STANDARD_SCORE:
            return {"offset_ms": offset_ms, "confidence_ratio": confidence_ratio, "status": "low_confidence"}
        return {"offset_ms": offset_ms, "confidence_ratio": confidence_ratio, "status": "ok"}
    except Exception as e:
        logging.error(f"Offset error {song_path}: {e}")
        return {"offset_ms": 0, "confidence_ratio": 0.0, "status": "error"}

