"""CLI entry point — processes a local video *or* an S3 URL.

Usage
-----
    python -m src <local-video.mp4> [output.mp4]
    python -m src s3://bucket/path/video.mp4
"""

import os
import sys
import tempfile
import time

from .config import OUTPUT_DIR
from .extraction import extract_clips
from .motion import compute_motion, find_peaks
from .storage import S3Storage, build_s3_url, output_key_for, parse_s3_url

__all__ = ["main"]


# ── Core pipeline ───────────────────────────────────────────────────────────
def process_video(video_path: str, output_path: str) -> bool:
    """Run motion analysis → peak detection → clip extraction.

    Returns ``True`` on success, ``False`` when no peaks are found.
    """
    t0 = time.time()
    fps, scores = compute_motion(video_path)
    t1 = time.time()
    print(f"  ⏱  Motion analysis: {t1 - t0:.1f}s")

    peaks = find_peaks(scores, fps)
    t2 = time.time()
    print(f"  ⏱  Peak detection:  {t2 - t1:.2f}s")

    if not peaks:
        return False

    extract_clips(video_path, peaks, fps, output_path)
    t3 = time.time()
    print(f"  ⏱  Clip extraction: {t3 - t2:.1f}s")

    return True


# ── Local mode ──────────────────────────────────────────────────────────────
def _run_local(video_path: str, output_path: str | None = None) -> int:
    if output_path is None:
        output_path = os.path.join(OUTPUT_DIR, "highlights.mp4")

    print(f"Pipeline: {video_path}")
    print("-" * 60)

    t_start = time.time()
    ok = process_video(video_path, output_path)
    t_total = time.time() - t_start

    if not ok:
        print("  ⛔  No peaks above threshold. Try lowering MOTION_THRESHOLD.")
        return 1

    print(f"  ⏱  Total:           {t_total:.1f}s")
    return 0


# ── S3 mode ─────────────────────────────────────────────────────────────────
def _run_s3(s3_url: str) -> int:
    bucket, key = parse_s3_url(s3_url)
    output_key = output_key_for(key)
    output_s3_url = build_s3_url(bucket, output_key)

    print(f"Pipeline: {s3_url}")
    print(f"  Output:  {output_s3_url}")
    print("-" * 60)

    storage = S3Storage()
    t_start = time.time()

    # Temporary local paths
    suffix = os.path.splitext(key)[1] or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        input_path = tmp.name
    output_path = input_path + "_out" + suffix

    try:
        # 1. Download
        t0 = time.time()
        storage.download(s3_url, input_path)
        print(f"  ⏱  Download:        {time.time() - t0:.1f}s")

        # 2. Process
        ok = process_video(input_path, output_path)
        if not ok:
            print("  ⛔  No peaks above threshold. Try lowering MOTION_THRESHOLD.")
            return 1

        # 3. Upload
        t0 = time.time()
        storage.upload(output_path, output_s3_url)
        print(f"  ⏱  Upload:          {time.time() - t0:.1f}s")

        t_total = time.time() - t_start
        print(f"  ⏱  Total:           {t_total:.1f}s")
        print(f"\n✅  Done → {output_s3_url}")
        return 0

    finally:
        for p in (input_path, output_path):
            try:
                os.remove(p)
            except FileNotFoundError:
                pass


# ── CLI ─────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Returns an exit code (0 = success).
    """
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        print(
            "Usage:\n"
            "  python -m src <local-video.mp4> [output.mp4]\n"
            "  python -m src s3://bucket/path/video.mp4\n"
        )
        return 1

    first = args[0]

    if first.startswith("s3://"):
        return _run_s3(first)
    else:
        output = args[1] if len(args) > 1 else None
        return _run_local(first, output)


if __name__ == "__main__":
    sys.exit(main())
