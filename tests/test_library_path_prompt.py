"""prompt_library_path() -- ask for the Clone Hero library folder at startup.

Previously homeFolder was hardcoded in main(), requiring a source edit to
point the script at a different library. Mirrors the existing
prompt_confidence_threshold() pattern: prompts with a default (press Enter
to accept it) only when interactive and stdin is a real tty, otherwise
falls back to the default silently.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'CH-VideoScript.py'

_spec = importlib.util.spec_from_file_location('ch_video_script_library_path_test', MODULE_PATH)
CH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CH)


def test_defaults_when_not_interactive(monkeypatch):
	monkeypatch.setattr(CH.sys.stdin, 'isatty', lambda: True)
	assert CH.prompt_library_path(default=r'M:\Songs', interactive=False) == r'M:\Songs'


def test_defaults_when_not_a_tty_even_if_interactive(monkeypatch):
	monkeypatch.setattr(CH.sys.stdin, 'isatty', lambda: False)
	assert CH.prompt_library_path(default=r'M:\Songs', interactive=True) == r'M:\Songs'


def test_prompts_and_returns_entered_path(monkeypatch):
	monkeypatch.setattr(CH.sys.stdin, 'isatty', lambda: True)
	monkeypatch.setattr('builtins.input', lambda prompt: r'D:\Other\Songs')

	result = CH.prompt_library_path(default=r'M:\Songs', interactive=True)

	assert result == r'D:\Other\Songs'


def test_empty_input_falls_back_to_default(monkeypatch):
	monkeypatch.setattr(CH.sys.stdin, 'isatty', lambda: True)
	monkeypatch.setattr('builtins.input', lambda prompt: '')

	result = CH.prompt_library_path(default=r'M:\Songs', interactive=True)

	assert result == r'M:\Songs'


def test_strips_whitespace_from_entered_path(monkeypatch):
	monkeypatch.setattr(CH.sys.stdin, 'isatty', lambda: True)
	monkeypatch.setattr('builtins.input', lambda prompt: '  D:\\Other\\Songs  ')

	result = CH.prompt_library_path(default=r'M:\Songs', interactive=True)

	assert result == r'D:\Other\Songs'
