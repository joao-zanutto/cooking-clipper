"""Clip extraction — single-pass ffmpeg ``select`` filter."""

import os
import subprocess

import numpy as np

from .config import CLIP_DURATION


def extract_clips(
    video_path: str, peaks: list, fps: float, output: str
) -> None:
    """Extract all peak windows in a single ffmpeg pass via the ``select`` filter.

    The video is decoded **once**; only the frames belonging to the desired
    segments are kept, re-timestamped, and encoded into the final output.
    No temporary files or concatenation step are needed.
    """
    num_clips = len(peaks)
    if num_clips == 0:
        print("  No clips to extract.")
        return

    # Build select filter expressions
    clip_exprs: list[str] = []
    for start_f, _end_f, _score in peaks:
        start_t = start_f / fps
        end_t = start_t + CLIP_DURATION
        clip_exprs.append(f"between(t,{start_t:.3f},{end_t:.3f})")

    select_expr = "+".join(clip_exprs)

    print(f"\n  Extracting {num_clips} clips in a single pass...")
    for i, (start_f, _end_f, score) in enumerate(peaks):
        start_t = start_f / fps
        print(f"    {i + 1:2d}.  {start_t:.1f}s  (motion score: {score:.1f})")

    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)

    cmd: list[str] = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        video_path,
        "-vf",
        f"select='{select_expr}',setpts=N/FRAME_RATE/TB",
        "-af",
        f"aselect='{select_expr}',asetpts=N/SR/TB",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        output,
    ]
    subprocess.run(cmd, check=True)

    total = num_clips * CLIP_DURATION
    print(f"\n  Saved: {output}  ({num_clips} clips → {total:.1f}s total)")
