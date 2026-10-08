"""Byte-exact RGBA decoding defaults shared by playback and thumbnails.

Looping, pacing and output frame limits belong to their individual callers.
Each caller copies these tuples before adding its own options.
"""

INPUT_PARAMS = ('-c:v', 'libvpx-vp9', '-threads', '1', '-filter_threads', '1')
OUTPUT_PARAMS = ('-threads', '1')
