"""Motion analysis — frame-differencing-based peak detection."""

import concurrent.futures

import cv2
import numpy as np

from .config import (
    BLANKING_GAP,
    CHANGE_THRESHOLD,
    CLIP_DURATION,
    MAX_WORKERS,
    MOTION_THRESHOLD,
)


# ── Parallel chunk worker ───────────────────────────────────────────────────
def _analyze_chunk(
    video_path: str, read_start: int, read_end: int, is_first: bool
):
    """Process frames [read_start, read_end) and return (scores, last_gray).

    For the first chunk (is_first=True), scores[0] = 0.0.
    For subsequent chunks, the frame at *read_start* is used only as the
    "previous" frame for the first diff — no score is emitted for it.
    This creates a 1-frame overlap that ensures gapless motion scores
    across chunk boundaries.
    """
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, read_start)

    ret, prev = cap.read()
    if not ret:
        cap.release()
        return [], None

    prev_gray = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)
    prev_gray = cv2.GaussianBlur(prev_gray, (5, 5), 1.0)

    h, w = prev_gray.shape
    total_pixels = h * w

    scores: list[float] = []
    if is_first:
        scores.append(0.0)

    for _ in range(read_start + 1, read_end):
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 1.0)
        diff = cv2.absdiff(prev_gray, gray)
        significant = np.sum(diff > CHANGE_THRESHOLD)
        scores.append(significant / total_pixels * 100)
        prev_gray = gray

    cap.release()
    return scores, prev_gray


# ── Motion analysis ─────────────────────────────────────────────────────────
def compute_motion(video_path: str):
    """Return ``(fps, scores_array)`` where ``scores[t]`` = percentage of frame
    that changed significantly between frame *t-1* and *t*.

    The video is split into chunks and processed in parallel via
    :class:`~concurrent.futures.ProcessPoolExecutor`.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    duration = total_frames / fps
    print(f"  Video: {duration:.1f}s @ {fps:.2f} fps = {total_frames} frames")

    # Determine chunk size  (at least 200 frames per chunk)
    num_workers = min(MAX_WORKERS, max(1, total_frames // 200))
    chunk_size = total_frames // num_workers if num_workers > 0 else total_frames

    # Build chunk descriptors — each chunk overlaps the previous by 1 frame
    chunks: list[tuple] = []
    for i in range(num_workers):
        read_start = max(0, i * chunk_size - (1 if i > 0 else 0))
        read_end = total_frames if i == num_workers - 1 else (i + 1) * chunk_size
        chunks.append((video_path, read_start, read_end, i == 0))

    print(f"  Analyzing {num_workers} chunks in parallel ({MAX_WORKERS} workers)...")

    with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(_analyze_chunk, *c) for c in chunks]
        concurrent.futures.wait(futures)
        results = [f.result() for f in futures]

    # Merge scores in chunk order
    all_scores: list[float] = []
    for scores, _ in results:
        all_scores.extend(scores)

    scores_arr = np.array(all_scores, dtype=np.float64)
    if len(scores_arr) != total_frames:
        raise RuntimeError(
            f"Score length mismatch: {len(scores_arr)} vs {total_frames}"
        )

    print(f"  Motion analysis complete ({len(scores_arr)} frames)")
    return fps, scores_arr


# ── Peak detection ──────────────────────────────────────────────────────────
def find_peaks(scores: np.ndarray, fps: float):
    """Find all motion peaks above threshold.

    Returns a list of ``(start_frame, end_frame, window_sum_score)`` tuples
    sorted chronologically.  Only peaks whose score >=
    ``MOTION_THRESHOLD * max_score`` are kept.
    """
    window_frames = int(CLIP_DURATION * fps)
    min_gap_frames = int(BLANKING_GAP * fps)

    if window_frames < 1:
        raise RuntimeError(
            "CLIP_DURATION too short for this video's frame rate"
        )

    # Sliding-window sum
    window_sums = np.convolve(scores, np.ones(window_frames), mode="valid")
    max_score = window_sums.max()
    if max_score <= 0:
        print("  No motion detected — try lowering CHANGE_THRESHOLD")
        return []

    cutoff = max_score * MOTION_THRESHOLD
    print(
        f"  Motion: max={max_score:.1f}  cutoff={cutoff:.1f}  "
        f"(threshold={MOTION_THRESHOLD})"
    )

    # Iteratively grab the highest remaining peak, blank it, repeat
    working = window_sums.copy()
    peaks: list[tuple[int, int, float]] = []
    while True:
        peak_frame = int(working.argmax())
        score = float(working[peak_frame])
        if score < cutoff:
            break

        peaks.append((peak_frame, peak_frame + window_frames, score))

        # Blank this region + gap so we find the next distinct peak
        start_blank = max(0, peak_frame - min_gap_frames)
        end_blank = min(
            len(working), peak_frame + window_frames + min_gap_frames
        )
        working[start_blank:end_blank] = 0

    peaks.sort(key=lambda p: p[0])
    return peaks
