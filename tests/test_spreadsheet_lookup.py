import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'CH-VideoScript.py'

spec = importlib.util.spec_from_file_location('ch_video_script', MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_parse_folder_name_handles_artist_title_split():
    artist, title = module.parse_folder_name('Artist - Song Title')
    assert artist == 'Artist'
    assert title == 'Song Title'


def test_find_sheet_match_prefers_artist_and_title():
    rows = [
        {'Artist': 'Artist', 'Song': 'Song Title', 'Offset': '-1000', 'Video Source': 'Official Music Video'},
        {'Artist': 'Artist', 'Song': 'Other', 'Offset': '1000', 'Video Source': 'Official Music Video'},
    ]
    match = module.find_sheet_match(rows, 'Artist', 'Song Title')
    assert match is not None
    assert match['Offset'] == '-1000'


def test_strip_title_noise_removes_bass_pedal_variants():
    assert module.strip_title_noise('Song Title (2x Bass Pedal)') == 'Song Title'
    assert module.strip_title_noise('Song Title (4x Bass Pedal)') == 'Song Title'


def test_has_existing_video_detects_video_files(tmp_path):
    song_folder = tmp_path / 'Artist - Song'
    song_folder.mkdir()
    (song_folder / 'video.mp4').write_bytes(b'fake')

    exists, video_path = module.has_existing_video(str(song_folder))
    assert exists is True
    assert video_path is not None
    assert video_path.name == 'video.mp4'


def test_prompt_confidence_threshold_defaults_when_non_interactive(monkeypatch):
    monkeypatch.setattr(module.sys.stdin, 'isatty', lambda: False)
    assert module.prompt_confidence_threshold(default=70) == 70


def test_calculate_cochran_sample_size_scaling():
    assert module.calculate_cochran_sample_size(1) == 1
    assert module.calculate_cochran_sample_size(10) >= 1
    assert module.calculate_cochran_sample_size(100) >= 1
    assert module.calculate_cochran_sample_size(1000) <= 1000


def test_summarize_confidence_statistics():
    stats = module.summarize_confidence_statistics([10, 20, 20, 30])
    assert stats['count'] == 4
    assert stats['mean'] == 20
    assert stats['median'] == 20
    assert stats['mode'] == 20
    assert stats['min'] == 10
    assert stats['max'] == 30
    assert stats['std_dev'] > 0


def test_strip_title_noise_removes_pedal_variants():
    assert module.strip_title_noise('Song Title (2x Bass Pedal)') == 'Song Title'
    assert module.strip_title_noise('Song Title (2x Pedal)') == 'Song Title'
    assert module.strip_title_noise('Song Title [4x Pedal Expert]') == 'Song Title'


def test_is_difficulty_search_result_detects_chart_difficulty():
    assert module.is_difficulty_search_result('Song Title Expert')
    assert module.is_difficulty_search_result('Song Title - Hard')
    assert module.is_difficulty_search_result('Song Title Medium Plus')
    assert not module.is_difficulty_search_result('Official Music Video')
    assert not module.is_difficulty_search_result('Song Title (Live)')


def test_search_youtube_candidates_excludes_difficulty_titles(monkeypatch):
    class DummyYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, query, download=False):
            return {
                'entries': [
                    {'id': 'abc123', 'title': 'Song Title Expert'},
                    {'id': 'def456', 'title': 'Song Title Official Video'},
                    {'id': 'ghi789', 'title': 'Song Title Hard'},
                ]
            }

    monkeypatch.setattr(module.yt_dlp, 'YoutubeDL', DummyYDL)
    candidates = module.search_youtube_candidates('Song Title', 'Artist', 'Song Title', max_results=3)
    assert len(candidates) == 1
    assert candidates[0]['url'] == 'https://www.youtube.com/watch?v=def456'
    assert 'Official Video' in candidates[0]['title']


def test_search_youtube_candidates_handles_network_error(monkeypatch, capsys):
    class FailingYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, query, download=False):
            raise RuntimeError('network failure')

    monkeypatch.setattr(module.yt_dlp, 'YoutubeDL', FailingYDL)
    candidates = module.search_youtube_candidates('Song Title', 'Artist', 'Song Title', max_results=3)
    captured = capsys.readouterr()

    assert candidates == []
    assert "WARNING: YouTube search failed" in captured.out
    assert module.search_failures == 1
