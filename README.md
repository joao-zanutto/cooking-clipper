# Cooking Clipper

Extracts the most visually active moments from cooking footage and concatenates them into a single highlight reel.

Detects motion like chopping, stirring, pouring, ingredient additions — not camera shake or static talking heads.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run on your video
python split.py pao5.mp4

# Or specify output path
python split.py pao5.mp4 output/highlights.mp4
```

## Configuration

Copy `.env.example` to `.env` and tweak:

| Variable           | Default   | Description                                                              |
| ------------------ | --------- | ------------------------------------------------------------------------ |
| `CLIP_DURATION`    | `2.5`     | Length of each extracted clip (seconds)                                  |
| `MOTION_THRESHOLD` | `0.15`    | Sensitivity (0–1). Lower = more clips, Higher = fewer, stricter clips    |
| `CHANGE_THRESHOLD` | `20`      | Pixel intensity diff to count as "motion" (5–50). Lower = more sensitive |
| `BLANKING_GAP`     | `3.0`     | Minimum gap between consecutive clips to avoid overlap                   |
| `OUTPUT_DIR`       | `output`  | Where to save the final video                                            |
| `MAX_WORKERS`      | CPU count | Parallel workers for motion analysis only                                |

### Tuning Tips

- **Too few / no clips** → lower `MOTION_THRESHOLD` (e.g. `0.05`) or lower `CHANGE_THRESHOLD` (e.g. `10`)
- **Too many clips / noise** → raise `MOTION_THRESHOLD` (e.g. `0.3`) or raise `CHANGE_THRESHOLD` (e.g. `30`)
- **Clips too short / long** → adjust `CLIP_DURATION`
- **Camera shake being detected** → raise `CHANGE_THRESHOLD` to `30` or `40`

## How It Works

1. **Frame differencing** — compares every consecutive frame, blurred to reduce noise
2. **Thresholding** — only counts pixels that changed significantly (ignores jitter/shake)
3. **Sliding window** — sums motion over `CLIP_DURATION` windows
4. **Peak detection** — finds all windows above `MOTION_THRESHOLD × max_score`
5. **Single-pass extraction** — uses ffmpeg's `select` filter to extract all clips in one decode pass, then concatenates them automatically

### Performance

- **Motion analysis** is parallelized across CPU cores (`ProcessPoolExecutor`) — ~4× faster on 4 cores
- **Clip extraction** uses a single ffmpeg pass with the `select` filter — decodes the video once instead of once per clip (~4× faster than sequential extraction)
