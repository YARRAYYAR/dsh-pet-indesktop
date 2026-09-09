"""Verify real FFmpeg filtering: hidden RGB must not contaminate the silhouette."""
import subprocess

import imageio_ffmpeg
import numpy as np

from pet.webm_clip import _decode_filter


def test_transparent_rgb_does_not_leak_into_downsampled_edges():
    image = np.zeros((16, 16, 4), dtype=np.uint8)
    image[:, :, 1] = 255  # invisible green outside the white foreground
    image[3:13, 3:13] = (255, 255, 255, 255)
    result = subprocess.run([
        imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-f', 'rawvideo',
        '-pix_fmt', 'rgba', '-s', '16x16', '-i', '-', '-frames:v', '1',
        '-vf', _decode_filter(8, 8), '-pix_fmt', 'rgba', '-f', 'rawvideo', '-',
    ], input=image.tobytes(), capture_output=True, check=True)
    output = np.frombuffer(result.stdout, np.uint8).reshape(8, 8, 4)
    edge = output[(output[:, :, 3] > 0) & (output[:, :, 3] < 255)]
    assert len(edge) > 0
    assert np.max(np.ptp(edge[:, :3].astype(int), axis=1)) <= 2
    assert np.all(output[3:5, 3:5] == 255)
    assert np.all(output[0, :, 3] == 0)
