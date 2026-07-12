"""probe_frame_rate() JSON-parsing logic (VFR vs CFR), and reencode_to_cfr()'s
atomic-write/no-backup contract.

VFR causes progressive, cumulative audio/video desync that a single static
video_start_time offset cannot fix -- source video must be normalized to
constant frame rate before offset computation. Per the plan, the ffprobe/
ffmpeg subprocess calls themselves are validated manually (mocking ffmpeg has
low value for a personal script); these tests cover the parsing logic and the
atomic-overwrite mechanics with mocked subprocess output.
"""

from unittest.mock import MagicMock, patch

import clonehero_video_offset as module

VFR_FFPROBE_JSON = """
{
    "streams": [
        {
            "r_frame_rate": "30/1",
            "avg_frame_rate": "29970/1000"
        }
    ]
}
"""

CFR_FFPROBE_JSON = """
{
    "streams": [
        {
            "r_frame_rate": "30/1",
            "avg_frame_rate": "30/1"
        }
    ]
}
"""

NO_VIDEO_STREAM_JSON = """
{
    "streams": []
}
"""


def _fake_completed_process(stdout):
	proc = MagicMock()
	proc.stdout = stdout
	return proc


def test_detects_vfr_when_rates_differ():
	with patch.object(module.subprocess, "run", return_value=_fake_completed_process(VFR_FFPROBE_JSON)):
		assert module.probe_frame_rate("video.mp4") is True


def test_detects_cfr_when_rates_match():
	with patch.object(module.subprocess, "run", return_value=_fake_completed_process(CFR_FFPROBE_JSON)):
		assert module.probe_frame_rate("video.mp4") is False


def test_returns_false_when_no_video_stream_found():
	with patch.object(module.subprocess, "run", return_value=_fake_completed_process(NO_VIDEO_STREAM_JSON)):
		assert module.probe_frame_rate("video.mp4") is False


def test_returns_false_and_logs_on_ffprobe_failure():
	with patch.object(module.subprocess, "run", side_effect=OSError("ffprobe not found")):
		assert module.probe_frame_rate("video.mp4") is False


def test_reencode_to_cfr_overwrites_in_place_with_no_backup(tmp_path):
	video = tmp_path / "video.mp4"
	video.write_bytes(b"original-bytes")

	def fake_ffmpeg_run(cmd, **kwargs):
		# find the -y-preceded output path (last argument) and write "re-encoded" content,
		# simulating a successful CFR re-encode without needing real ffmpeg
		out_path = cmd[-1]
		with open(out_path, "wb") as f:
			f.write(b"reencoded-bytes")
		return MagicMock(returncode=0)

	with patch.object(module.subprocess, "run", side_effect=fake_ffmpeg_run):
		result = module.reencode_to_cfr(video)

	assert result is True
	assert video.read_bytes() == b"reencoded-bytes"
	# no .cfr_tmp/.bak/temp file left behind in the folder
	remaining = list(tmp_path.iterdir())
	assert remaining == [video]


def test_reencode_to_cfr_leaves_original_untouched_on_failure(tmp_path):
	video = tmp_path / "video.mp4"
	video.write_bytes(b"original-bytes")

	with patch.object(module.subprocess, "run", side_effect=OSError("ffmpeg crashed")):
		result = module.reencode_to_cfr(video)

	assert result is False
	assert video.read_bytes() == b"original-bytes"
	remaining = list(tmp_path.iterdir())
	assert remaining == [video]
