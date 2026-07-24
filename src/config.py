"""Application configuration loaded from environment / .env file."""

import multiprocessing
import os

from dotenv import load_dotenv

load_dotenv()

# ── Processing ──────────────────────────────────────────────────────────────
CLIP_DURATION = float(os.getenv("CLIP_DURATION", "2.5"))
MOTION_THRESHOLD = float(os.getenv("MOTION_THRESHOLD", "0.15"))
CHANGE_THRESHOLD = int(os.getenv("CHANGE_THRESHOLD", "20"))
BLANKING_GAP = float(os.getenv("BLANKING_GAP", "3.0"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
MAX_WORKERS = max(1, int(os.getenv("MAX_WORKERS", "0")) or multiprocessing.cpu_count())

# ── S3-compatible storage ───────────────────────────────────────────────────
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://seaweedfs.local:8333")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", "")
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", "")
S3_SPLIT_SUFFIX = os.getenv("S3_SPLIT_SUFFIX", "_Split")
S3_OUTPUT_PREFIX = os.getenv("S3_OUTPUT_PREFIX", "_output/")
