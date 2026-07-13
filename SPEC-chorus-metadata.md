# Spec: Chorus Encore Metadata Enrichment for clonehero-video-downloader

## Objective

Song folders processed by `CH-VideoScript.py` often end up with a sparse `song.ini` — the source video rarely carries fields like year, genre, charter, or album, and today there's no automated way to fill those in.

This feature adds a pass that looks up each song on the Chorus Encore chart database (`enchor.us`) by artist+title, and fills in any **blank or missing** `song.ini` fields from a confident match. It never overwrites a field that already has a value — the pipeline's own output and any manual edits the user has made both take priority over Chorus data.

**User**: same solo hobbyist, local/interactive/no-auth trust model as the rest of this project.

**Success looks like**: running the enrichment pass across the library leaves every `song.ini` with whatever of `{year, genre, charter, album}` Chorus has on record for a confident match, and changes nothing else — no field that already had a value is ever touched.

## Decisions Made During the 2026-07-13 Bridge Briefing

- **Album art is out of scope for v1, confirmed, not an open question.** Live browser inspection of `enchor.us`'s Advanced Search UI (the richest available surface for this data) shows zero album-art field or control anywhere — Name/Artist/Album/Genre/Year/Charter/Length/Intensity/NPS/hashes/feature-flags are all present, album art is not. This is real evidence the service doesn't track it as queryable data, not just an undocumented gap. If this changes later it needs its own spec revision, not a re-opened question here.
- **The real API host is confirmed**: `https://api.enchor.us/search` (found via live browser network inspection). The `Paturages/chorus` GitHub README's documented host, `chorus.fightthe.pw`, is **confirmed dead** (HTTP 404) — that README describes a version of the project that no longer matches production.
- **RESOLVED (2026-07-14, Task 0): the exact request/response schema is now captured**, sourced directly from reading [Bridge](https://github.com/Geomitron/Bridge)'s actual TypeScript source (`search.service.ts`/`search.interface.ts`) rather than guessed or browser-reverse-engineered. See Tech Stack below for the real shape. Shared with `SPEC-duplicate-detection.md` — both specs' `chorus_client.py` usage is now built on a confirmed-real contract, not an assumption.
- **Every Chorus-sourced field must be sanitized before it touches `song.ini`.** Fields are spliced into the file via regex substitution (not `configparser`), so an unsanitized value containing control characters, embedded `[`/`]`/`;`/`#`, embedded newlines, or invalid encoding could corrupt the file or desync subsequent keys. This is now a hard requirement, not an implicit assumption.
- **This feature needs the same per-item audit logging and aggregate summary its sibling specs already commit to.** The original draft left failures/skips silent; that's inconsistent with `SPEC-chart-rename.md` ("log every rename and every relocation with its reason") and `SPEC-duplicate-detection.md` ("log every keeper decision with its full score breakdown"), and was flagged as a real gap during review.

## Tech Stack

- **RESOLVED (2026-07-14, Task 0): real request/response schema sourced directly from Bridge's actual TypeScript source** (`Geomitron/Bridge`, `src-angular/app/core/services/search.service.ts` and `src-shared/interfaces/search.interface.ts`), not guessed and not browser-reverse-engineered. Confirms `https://api.enchor.us` is the real, currently-live base URL Bridge itself uses (`environment.prod.ts`).
- **Reuses `chorus_client.py` from `SPEC-duplicate-detection.md` rather than building a second Chorus client** — both features need the same artist/title lookup. This spec adds `search_by_artist_title()` to it, built on the advanced-search endpoint below.
- **Real endpoint for this spec's use case**: `POST https://api.enchor.us/search/advanced` — NOT a `GET .../search?query=...` as the dead README implied. Body is a JSON object matching Bridge's `AdvancedSearchSchema` (zod): every field must be present (nullable, not optional), so a lookup request sends the full shape with only `name`/`artist` populated and everything else at its neutral/null default:
  ```json
  {
    "per_page": 1, "page": 1,
    "name": {"value": "Kryptonite", "exact": false, "exclude": false},
    "artist": {"value": "3 Doors Down", "exact": false, "exclude": false},
    "album": {"value": "", "exact": false, "exclude": false},
    "genre": {"value": "", "exact": false, "exclude": false},
    "year": {"value": "", "exact": false, "exclude": false},
    "charter": {"value": "", "exact": false, "exclude": false},
    "instrument": null, "difficulty": null, "drumType": null, "drumsReviewed": true,
    "minLength": null, "maxLength": null, "minIntensity": null, "maxIntensity": null,
    "minAverageNPS": null, "maxAverageNPS": null, "minMaxNPS": null, "maxMaxNPS": null,
    "modifiedAfter": null, "hash": null,
    "hasSoloSections": null, "hasForcedNotes": null, "hasOpenNotes": null, "hasTapNotes": null,
    "hasLyrics": null, "hasVocals": null, "hasRollLanes": null, "has2xKick": null,
    "hasIssues": null, "hasVideoBackground": null, "modchart": null,
    "sort": null, "source": "bridge"
  }
  ```
- **Real response fields (from `SearchResult`/`ChartData` in `search.interface.ts`, not the dead README's guessed shape)**: `{found, out_of, page, search_time_ms, data: [...]}`; each `data` entry has `name`, `artist`, `album`, `genre`, `year`, `charter` — all `string | null` — plus `chartId`, `songId`, `md5`, `chartHash`, `song_length` (ms), many `diff_*` fields, and more not needed here.
- **No album-art field anywhere in the real response** — confirmed absolutely, not just "undocumented." There's an `albumArtMd5` (a hash of the art file, presumably for the site's own caching), but no URL or binary data for the art itself. This is stronger confirmation of the Decisions-above finding: album art is out of scope for v1, full stop.
- Response fields `year`/`genre`/`charter`/`album` are exactly the field names this spec already planned to fill — no change needed to the fill logic, only the request/lookup mechanism.
- **Sanitization**: a strict allow-list sanitizer applied to every field before it reaches the ini-patch regex path — strip control characters and newlines, reject/strip embedded `[`, `]`, `;`, `#`, enforce a max length, validate UTF-8 decoding. Applied uniformly regardless of "single local user" trust framing, because the file format itself (not a network boundary) is the actual attack surface here.
- `song.ini` multi-key fill: a new function generalizing `patch_song_ini()`'s byte-preserving regex + atomic-write approach (`CH-VideoScript.py`) to fill several keys in one pass instead of just `video_start_time`, with the same CRLF/LF and comment preservation guarantees.
- No new dependency beyond whatever HTTP client `chorus_client.py` ends up using in the dedupe spec (e.g. `requests`) — this feature doesn't introduce a second one.

## Commands

```
Run:      python CH-VideoScript.py --enrich-metadata   (standalone flag vs. folded into a combined
                                                           "finalize" pass alongside chart-rename — TBD at /plan)
Dry run:  python CH-VideoScript.py --enrich-metadata --dry-run   (logs planned fills, writes nothing)
Test:     pytest tests/ -v
```

## Project Structure

```
chorus_client.py (shared with SPEC-duplicate-detection.md, extended not duplicated)
    search_by_artist_title(artist, title) -> dict | None
        Best-effort: catches and logs network/lookup failures, returns None on
        no-match or error, never raises — same contract the dedupe spec requires.
        Built from Bridge's (Geomitron) client source, not a guessed schema.

CH-VideoScript.py (or a new clonehero_metadata_enrich.py — TBD at /plan)
    sanitize_chorus_field(value) -> str | None
        Strict allow-list sanitizer: strips control chars/newlines, rejects
        embedded [ ] ; #, enforces max length, validates UTF-8. Returns None
        if the value can't be made safe, in which case that field is skipped
        (never partially sanitized and written).
    fill_song_ini_metadata(song_folder, chorus_result) -> {status, detail}
        Blank-only multi-key ini patch. Statuses: 'filled' (>=1 field written),
        'no_change' (song.ini already complete, or no confident match), 'no_match'
        (Chorus lookup returned nothing usable), 'error' (lookup or write failed).
        Mirrors the {status, detail} convention scan_song_folder_video() and
        scan_song_folder_chart_names() already use.
    enrich_song_ini_metadata_library(home_folder) -> None
        Aggregate pass + printed summary, mirrors scan_and_fix_video_library() /
        scan_and_fix_chart_library() -- logs every song's outcome and reason,
        never silently skips.

tests/
    test_chorus_metadata_fill.py      -> Blank-only fill logic against synthetic song.ini +
                                          a mocked chorus_client response, including the
                                          "field already has a value, must NOT change" case
    test_chorus_lookup_confidence.py  -> Match confidence / no-match / ambiguous-multiple-
                                          results handling
    test_metadata_ini_patch.py        -> Byte-preserving multi-key patch mechanics, reusing
                                          patch_song_ini()'s proven approach
    test_chorus_field_sanitization.py -> Sanitizer against malicious/malformed field values
                                          (embedded brackets, newlines, control chars, bad
                                          encoding, oversized strings) -- must never let an
                                          unsafe value reach the ini-patch regex path

README.md  -> updated to document --enrich-metadata, which fields it can fill, and that
              album art is explicitly not supported (with the reason)
```

## Code Style

Match the existing project exactly — same shape as `patch_song_ini()`, generalized to multiple keys, with sanitization in front:

```python
FILLABLE_INI_KEYS = ("year", "genre", "charter", "album")
_UNSAFE_INI_CHARS_RE = re.compile(r"[\[\];#\r\n]")


def sanitize_chorus_field(value):
	#Chorus fields are spliced into song.ini via regex substitution, not parsed by
	#configparser -- an unsanitized value with a stray [, ], ;, #, or embedded
	#newline could corrupt the file or desync a later key. Reject rather than
	#partially clean, so a bad value never silently becomes a different bad value.
	if not isinstance(value, str) or not value.strip():
		return None
	if _UNSAFE_INI_CHARS_RE.search(value):
		return None
	try:
		value.encode("utf-8")
	except UnicodeEncodeError:
		return None
	return value.strip()[:200]


def fill_song_ini_metadata(song_folder, chorus_result):
	#only fills keys that are missing or blank in song.ini -- chorus_result never
	#overwrites a value the pipeline or the user already set, matching the
	#fill-blanks-only decision made before this spec was written
	ini_fields, target, line_ending = read_song_ini_fields(song_folder)  # reuses find_song_ini()
	if ini_fields is None:
		return {"status": "error", "detail": "no song.ini found"}

	to_fill = {}
	for key in FILLABLE_INI_KEYS:
		if ini_fields.get(key):
			continue
		safe_value = sanitize_chorus_field(chorus_result.get(key))
		if safe_value is not None:
			to_fill[key] = safe_value

	if not to_fill:
		return {"status": "no_change", "detail": "no fillable blank fields, or no safe values"}

	#same atomic tempfile.mkstemp + os.replace discipline as patch_song_ini()
	patch_song_ini_keys(target, to_fill, line_ending)
	return {"status": "filled", "detail": ", ".join(sorted(to_fill))}
```

- Tabs for indentation (matches existing files)
- Reuses `patch_song_ini()`'s regex-per-key approach rather than introducing `configparser` (which would reformat/reorder the file — the existing codebase deliberately avoids this)
- One function per discrete step, no classes
- Atomic writes (`tempfile.mkstemp` + `os.replace`) for `song.ini`
- Comments explain *why*, not *what*

## Testing Strategy

Same philosophy as the rest of the project: `song.ini` mutation is the real corruption risk, so the fill logic, sanitizer, and ini-patch mechanics get real unit tests against synthetic fixtures; real Chorus API round-trips are not unit tested.

- **Unit-tested**: blank-only fill semantics (`test_chorus_metadata_fill.py`) — critically, a `song.ini` with an existing `year` must come out byte-identical for that key even when Chorus returns a different value. Match-confidence / no-match / ambiguous-result handling (`test_chorus_lookup_confidence.py`). Byte-preserving multi-key patch mechanics (`test_metadata_ini_patch.py`), reusing `patch_song_ini()`'s existing test approach (CRLF/LF preservation, missing-key insertion, unrelated-line preservation). Sanitizer against adversarial field values (`test_chorus_field_sanitization.py`) — embedded `[`/`]`/`;`/`#`, embedded newlines, control characters, invalid UTF-8, and oversized strings must all be rejected, never partially cleaned and written.
- **Not unit-tested**: real Chorus API calls — validated via `--dry-run` against a real library sample. `chorus_client.py`'s mocked-response tests can now be built against the real, confirmed schema (Task 0) rather than a placeholder shape.
- No CI — local script, run on-demand.

## Boundaries

- **Always**:
  - Fill only blank/missing `song.ini` fields — never overwrite a field that already has any value
  - Sanitize every Chorus-sourced field through `sanitize_chorus_field()` before it reaches the ini-patch path; skip that field (not the whole song) if sanitization fails
  - Use atomic writes (temp file + `os.replace`) for `song.ini`, same as `patch_song_ini()`
  - Log every song's outcome (`filled`/`no_change`/`no_match`/`error`) with its reason, and print an aggregate summary at the end of a library run — mirroring `scan_and_fix_video_library()`'s and `scan_and_fix_chart_library()`'s reporting contract
  - Support `--dry-run` so planned fills can be reviewed before any file is touched
  - Degrade gracefully on a Chorus API failure or no-match — skip that song, never abort the run (mirrors `SPEC-duplicate-detection.md`'s "must not raise" contract for `chorus_client.py`)

- **Ask first**:
  - Exact field list to fill (this spec assumes `year`/`genre`/`charter`/`album`; widening it is a judgment call for `/plan`)
  - Match-confidence threshold for "confident enough to apply" a Chorus result

- **Never**:
  - Never overwrite an existing `song.ini` value, for any field
  - Never write a Chorus-sourced field that failed sanitization, even partially cleaned
  - Never touch `notes.chart`/`notes.mid`/audio files — this feature only ever writes to `song.ini`
  - Never let one song's lookup failure abort the whole run
  - Never attempt to source or write album art — out of scope for v1 (see Decisions above)

## Success Criteria

- [x] `chorus_client.py`'s real request/response schema sourced from Bridge's client code (not guessed) — done 2026-07-14, see Tech Stack
- [ ] Blank-only fill verified: a `song.ini` with an existing `year` is byte-identical after a run; one with a blank `year` gets filled from a confident match
- [ ] Sanitizer rejects every adversarial fixture (embedded brackets/newlines/control chars/bad encoding/oversized values) without writing anything unsafe
- [ ] Every song's outcome is logged with a reason; an aggregate summary prints at the end of a library run
- [ ] `--dry-run` touches zero files
- [ ] **Deferred to the user**: spot-check a sample of enriched `song.ini` files against the actual Chorus listing for correctness

## Open Questions

- Exact field list (this spec assumes `year`/`genre`/`charter`/`album`, all confirmed real response fields — see Tech Stack) and match-confidence threshold — needs a concrete proposal at `/plan`/Task 8, informed by real query results now that the schema is confirmed.
