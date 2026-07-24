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

---

# Operator — web UI for batch-processing videos in SeaweedFS

The operator runs inside your k3s cluster and exposes a **web UI** (port 8080)
where you select a project (S3 bucket), browse videos, configure per-video
processing parameters, and trigger Jobs.

## Architecture

```
                   ┌──────────────────────────────────┐
                   │  cooking-clipper-operator        │
                   │  ┌─────────┐  ┌───────────────┐  │
                   │  │Frontend │  │  Flask API     │  │
                   │  │(SPA)    │◄─┤  /api/buckets  │  │
                   │  └─────────┘  │  /process      │  │
                   │               │  /videos       │  │
                   │               └───────┬───────┘  │
                   └───────────────────────┼──────────┘
                                           │
              ┌────────────────────────────┼────────────┐
              │                            │            │
              ▼                            ▼            ▼
     ┌──────────────────┐      ┌──────────────────┐
     │  SeaweedFS S3    │      │  K8s Jobs        │
     │  (list buckets,  │      │  (cooking-clipper│
     │   list videos)   │      │   per video)     │
     └──────────────────┘      └──────────────────┘
```

## Quickstart

Build and deploy to your k3s cluster:

```bash
# 1. Build the operator image (from project root)
docker build -t cooking-clipper-operator:latest -f operator/Dockerfile .

# 2. Build the processing image
docker build -t cooking-clipper:latest .

# 3. Import into k3s (if using remote cluster via SSH)
docker save cooking-clipper:latest cooking-clipper-operator:latest | \
  ssh ubuntu@kube.local "k3s ctr images import -"

# 4. Deploy
kubectl apply -f operator/manifests/

# 5. Verify
kubectl -n cooking-clipper get pods

# 6. Access the UI (port-forward)
kubectl -n cooking-clipper port-forward svc/cooking-clipper-operator 8080:8080 &
open http://localhost:8080
```

## Usage

1. Open the web UI at `http://localhost:8080`
2. Select a project from the **bucket dropdown**
3. Adjust **clip duration**, **motion threshold**, and **change threshold** per video
4. Click **Process** on individual videos or **Process all unprocessed**
5. Watch job status update in real-time

## Output key scheme

```
_output/Split/{name}.mp4          # Highlight video
_output/Score/{name}_scores.json  # Motion scores
_output/Config/{name}_config.json # Processing config
```

The `_output/` prefix is automatically filtered from the video listing.

## Files

```
operator/
├── controller.py        # Flask web server + API + K8s integration
├── Dockerfile           # Operator image
├── requirements.txt     # Python deps (boto3 + kubernetes + flask)
├── frontend/
│   ├── index.html       # SPA
│   ├── app.js           # Frontend logic
│   └── style.css        # Dark theme styling
├── manifests/
│   ├── namespace.yml    # cooking-clipper namespace
│   ├── sa.yml           # ServiceAccount
│   ├── role.yml         # ClusterRole (jobs, pods)
│   ├── role-binding.yml # ClusterRoleBinding
│   ├── deployment.yml   # Operator Deployment (port 8080)
│   └── service.yml      # ClusterIP service
```

The processing **Job** uses the **main** `Dockerfile` (at repo root) — the same
`cooking-clipper:latest` image you use for single videos.

## API endpoints

| Method | Path                          | Description                                                                 |
| ------ | ----------------------------- | --------------------------------------------------------------------------- |
| GET    | `/`                           | Serves frontend SPA                                                         |
| GET    | `/api/buckets`                | List all S3 buckets                                                         |
| GET    | `/api/buckets/{name}/videos`  | List videos with processing status                                          |
| GET    | `/api/buckets/{name}/jobs`    | List recent jobs                                                            |
| POST   | `/api/buckets/{name}/process` | Trigger a Job `{key, clip_duration?, motion_threshold?, change_threshold?}` |
| GET    | `/api/status`                 | Health check                                                                |
