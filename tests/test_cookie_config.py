"""COOKIES_FILE / COOKIES_FROM_BROWSER priority in download_video_if_needed().

COOKIES_FILE (a static cookies.txt export) exists specifically to avoid
yt-dlp's "Could not copy Chrome cookie database" error, which happens because
cookiesfrombrowser can't read Chrome's cookie DB while Chrome is running.
When set, it must take priority over COOKIES_FROM_BROWSER so a user can rely
on it without needing Chrome closed during a run.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'CH-VideoScript.py'

_spec = importlib.util.spec_from_file_location('ch_video_script_cookie_test', MODULE_PATH)
CH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CH)


class _CapturingYDL:
	captured_opts = None

	def __init__(self, opts):
		_CapturingYDL.captured_opts = opts

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc, tb):
		return False

	def download(self, urls):
		pass


def test_cookies_file_takes_priority_when_both_set(monkeypatch, tmp_path):
	cookies_path = str(tmp_path / "cookies.txt")
	monkeypatch.setattr(CH, "COOKIES_FILE", cookies_path)
	monkeypatch.setattr(CH, "COOKIES_FROM_BROWSER", ("chrome",))
	monkeypatch.setattr(CH.yt_dlp, "YoutubeDL", _CapturingYDL)

	CH.download_video_if_needed("http://example.com/video", str(tmp_path), None)

	assert _CapturingYDL.captured_opts["cookiefile"] == cookies_path
	assert "cookiesfrombrowser" not in _CapturingYDL.captured_opts


def test_falls_back_to_cookies_from_browser_when_file_not_set(monkeypatch, tmp_path):
	monkeypatch.setattr(CH, "COOKIES_FILE", None)
	monkeypatch.setattr(CH, "COOKIES_FROM_BROWSER", ("chrome",))
	monkeypatch.setattr(CH.yt_dlp, "YoutubeDL", _CapturingYDL)

	CH.download_video_if_needed("http://example.com/video", str(tmp_path), None)

	assert _CapturingYDL.captured_opts["cookiesfrombrowser"] == ("chrome",)
	assert "cookiefile" not in _CapturingYDL.captured_opts


def test_no_cookies_option_when_both_unset(monkeypatch, tmp_path):
	monkeypatch.setattr(CH, "COOKIES_FILE", None)
	monkeypatch.setattr(CH, "COOKIES_FROM_BROWSER", None)
	monkeypatch.setattr(CH.yt_dlp, "YoutubeDL", _CapturingYDL)

	CH.download_video_if_needed("http://example.com/video", str(tmp_path), None)

	assert "cookiefile" not in _CapturingYDL.captured_opts
	assert "cookiesfrombrowser" not in _CapturingYDL.captured_opts
