"""Regression coverage for removing clonehero_video_offset.py's dead standalone CLI.

batch_process()/process_song()/the module-level update_ini() and the __main__ block
were only reachable via a CLI entry point CH-VideoScript.py never calls -- a race
risk against the same video_meta.json/song.ini files if ever run alongside the real
entry point. This test proves they're gone and the module used by CH-VideoScript.py
still imports and works.
"""

import clonehero_video_offset as module


def test_dead_batch_entry_points_are_removed():
	assert not hasattr(module, "batch_process")
	assert not hasattr(module, "process_song")
	# the module-level update_ini() (distinct from CH-VideoScript.py's update_ini_with_offset)
	# was only reachable via process_song()/batch_process()
	assert not hasattr(module, "update_ini")


def test_functions_used_by_ch_video_script_still_exist():
	assert hasattr(module, "extract_audio")
	assert hasattr(module, "compute_offset")
	assert hasattr(module, "find_song_audio")
	assert hasattr(module, "find_video_file")
