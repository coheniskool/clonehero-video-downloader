"""poll_typed_confidence() -- non-blocking stdin polling for the sampling loop.

Lets a user type a confidence level (0-100) and press Enter at any point
while the sampling loop is searching YouTube for sampled songs, ending
sampling early instead of always waiting for the whole sample to finish.

A background thread doing blocking input() was considered and rejected: it
would still be alive (and competing for stdin) when prompt_confidence_threshold()
later makes its own input() call for the non-early-exit path, since a thread
blocked in input() can't be cleanly cancelled. Non-blocking keystroke polling
(msvcrt, Windows-only -- this project is already Windows-specific) avoids
that hazard: it only reads a keystroke when explicitly polled, so it never
lingers after the sampling loop ends.
"""

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'CH-VideoScript.py'

_spec = importlib.util.spec_from_file_location('ch_video_script_confidence_interrupt_test', MODULE_PATH)
CH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CH)


class _FakeMsvcrt:
	def __init__(self, chars):
		self._chars = list(chars)

	def kbhit(self):
		return bool(self._chars)

	def getwch(self):
		return self._chars.pop(0)


def test_accumulates_characters_until_enter(monkeypatch):
	monkeypatch.setattr(CH, "msvcrt", _FakeMsvcrt(["7", "0"]))

	buffer, completed = CH.poll_typed_confidence("")

	assert buffer == "70"
	assert completed is None


def test_returns_completed_line_on_enter(monkeypatch):
	monkeypatch.setattr(CH, "msvcrt", _FakeMsvcrt(["7", "0", "\r"]))

	buffer, completed = CH.poll_typed_confidence("")

	assert buffer == ""
	assert completed == "70"


def test_backspace_removes_last_character(monkeypatch):
	monkeypatch.setattr(CH, "msvcrt", _FakeMsvcrt(["7", "5", "\x08", "0", "\r"]))

	buffer, completed = CH.poll_typed_confidence("")

	assert completed == "70"


def test_no_op_when_msvcrt_unavailable(monkeypatch):
	monkeypatch.setattr(CH, "msvcrt", None)

	buffer, completed = CH.poll_typed_confidence("existing")

	assert buffer == "existing"
	assert completed is None


def test_ctrl_c_raises_keyboard_interrupt(monkeypatch):
	monkeypatch.setattr(CH, "msvcrt", _FakeMsvcrt(["\x03"]))

	with pytest.raises(KeyboardInterrupt):
		CH.poll_typed_confidence("")


def test_no_keys_waiting_returns_buffer_unchanged(monkeypatch):
	monkeypatch.setattr(CH, "msvcrt", _FakeMsvcrt([]))

	buffer, completed = CH.poll_typed_confidence("12")

	assert buffer == "12"
	assert completed is None
