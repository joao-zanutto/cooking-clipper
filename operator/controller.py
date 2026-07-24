#!/usr/bin/env python3
"""Cooking Clipper Operator — web server with frontend + API.

Exposes a web UI and REST API to browse S3 buckets, list videos, configure
per-video processing parameters, and create Kubernetes Jobs.

Usage
-----
    python controller.py                          # runs in-cluster
    python controller.py --kubeconfig ~/.kube/config  # dev mode
"""

import argparse
import json
import logging
import os
import re
from urllib.request import urlopen

import boto3
from botocore.config import Config as BotoConfig
from flask import Flask, jsonify, request, send_from_directory
from kubernetes import client, config
from kubernetes.client.rest import ApiException

log = logging.getLogger("cooking-clipper-operator")

# ── Config from environment ─────────────────────────────────────────────────
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://seaweedfs.local:8333")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", "")
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", "")
S3_OUTPUT_PREFIX = os.getenv("S3_OUTPUT_PREFIX", "_output/")
SEAWEEDFS_MASTER_URL = os.getenv("SEAWEEDFS_MASTER_URL", "")

NAMESPACE = os.getenv("OPERATOR_NAMESPACE", "cooking-clipper")
JOB_IMAGE = os.getenv("JOB_IMAGE", "ghcr.io/joao-zanutto/cooking-clipper:latest")
JOB_IMAGE_PULL_POLICY = os.getenv("JOB_IMAGE_PULL_POLICY", "IfNotPresent")
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", "300"))

HOST = os.getenv("OPERATOR_HOST", "0.0.0.0")
PORT = int(os.getenv("OPERATOR_PORT", "8080"))

# Video file extensions we recognise
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".flv", ".wmv"}

# ── S3 helpers ──────────────────────────────────────────────────────────────


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        region_name=S3_REGION,
        aws_access_key_id=S3_ACCESS_KEY_ID or None,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY or None,
        config=BotoConfig(
            connect_timeout=15,
            read_timeout=30,
            retries={"max_attempts": 2},
        ),
    )


def _is_video(key: str) -> bool:
    """True if *key* looks like a video file and is not an output artifact."""
    # Skip output-prefixed files (_output/Split/..., _output/Score/..., etc.)
    if key.startswith(S3_OUTPUT_PREFIX):
        return False
    _, ext = os.path.splitext(key.lower())
    return ext in VIDEO_EXTS


def _list_buckets(s3) -> list[dict]:
    """List all S3 buckets.

    Uses the S3 ``list_buckets`` API first.  If that returns empty and
    *SEAWEEDFS_MASTER_URL* is configured, falls back to querying the
    SeaweedFS master for collections (which map to S3 buckets).
    """
    try:
        resp = s3.list_buckets()
        buckets = [
            {"name": b["Name"], "creation_date": b["CreationDate"].isoformat()}
            for b in resp.get("Buckets", [])
        ]
        if buckets:
            return buckets
    except Exception as exc:
        log.warning("S3 list_buckets failed: %s", exc)

    # Fallback: SeaweedFS master collections → S3 buckets
    if not SEAWEEDFS_MASTER_URL:
        return []

    try:
        url = f"{SEAWEEDFS_MASTER_URL.rstrip('/')}/dir/status"
        with urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode())
    except Exception as exc:
        log.warning("SeaweedFS master fallback failed: %s", exc)
        return []

    seen = set()
    buckets = []
    for layout in data.get("Topology", {}).get("Layouts", []):
        col = layout.get("collection", "")
        if col and col not in seen:
            seen.add(col)
            buckets.append({"name": col, "creation_date": ""})
    buckets.sort(key=lambda b: b["name"])
    return buckets


def _list_videos(s3, bucket: str) -> list[dict]:
    """List all video objects in *bucket* (filtered)."""
    try:
        resp = s3.list_objects_v2(Bucket=bucket)
    except Exception as exc:
        log.error("Failed to list bucket %s: %s", bucket, exc)
        return []

    videos = []
    for obj in resp.get("Contents", []):
        key = obj["Key"]
        if _is_video(key):
            videos.append({
                "key": key,
                "last_modified": obj["LastModified"].isoformat(),
                "size": obj["Size"],
            })
    videos.sort(key=lambda v: v["key"])
    return videos


def _output_key_for(key: str) -> str:
    """Return the output split key for a given video key."""
    name, _ = os.path.splitext(key)
    basename = os.path.basename(name)
    return f"{S3_OUTPUT_PREFIX}Split/{basename}.mp4"


def _scores_key_for(key: str) -> str:
    """Return the scores metadata key for a given video key."""
    name, _ = os.path.splitext(key)
    basename = os.path.basename(name)
    return f"{S3_OUTPUT_PREFIX}Score/{basename}_scores.json"


def _config_key_for(key: str) -> str:
    """Return the config metadata key for a given video key."""
    name, _ = os.path.splitext(key)
    basename = os.path.basename(name)
    return f"{S3_OUTPUT_PREFIX}Config/{basename}_config.json"


def _to_s3_http_url(bucket: str, key: str) -> str:
    """Convert a bucket+key pair to a direct S3 HTTP URL."""
    base = S3_ENDPOINT.rstrip("/")
    return f"{base}/{bucket}/{key}"


def _fetch_json_from_s3(s3, bucket: str, key: str) -> dict | None:
    """Fetch and parse a JSON object from S3, or return None if not found."""
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception:
        return None


def _check_already_processed(s3, bucket: str, video_key: str) -> bool:
    """True if the split output already exists for this video."""
    output_key = _output_key_for(video_key)
    try:
        s3.head_object(Bucket=bucket, Key=output_key)
        return True
    except Exception:
        return False


# ── Kubernetes helpers ──────────────────────────────────────────────────────


def _make_job_name(video_key: str) -> str:
    """Create a DNS-safe job name from the video key."""
    safe = re.sub(r"[^a-z0-9-]", "-", video_key.lower().replace("/", "-"))
    safe = re.sub(r"-+", "-", safe).strip("-")
    if len(safe) > 57:
        safe = safe[:57]
    return safe


def _build_job_manifest(
    bucket: str,
    video_key: str,
    clip_duration: float | None = None,
    motion_threshold: float | None = None,
    change_threshold: int | None = None,
) -> dict:
    """Build a Kubernetes Job manifest for processing one video."""
    job_name = _make_job_name(video_key)
    s3_url = f"s3://{bucket}/{video_key}"

    env = [
        {"name": "S3_ENDPOINT", "value": S3_ENDPOINT},
        {"name": "S3_REGION", "value": S3_REGION},
        {"name": "S3_ACCESS_KEY_ID", "value": S3_ACCESS_KEY_ID},
        {"name": "S3_SECRET_ACCESS_KEY", "value": S3_SECRET_ACCESS_KEY},
        {"name": "S3_OUTPUT_PREFIX", "value": S3_OUTPUT_PREFIX},
    ]
    if clip_duration is not None:
        env.append({"name": "CLIP_DURATION", "value": str(clip_duration)})
    if motion_threshold is not None:
        env.append({"name": "MOTION_THRESHOLD", "value": str(motion_threshold)})
    if change_threshold is not None:
        env.append({"name": "CHANGE_THRESHOLD", "value": str(change_threshold)})

    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": NAMESPACE,
            "labels": {
                "app": "cooking-clipper",
                "component": "job",
                "video-key": video_key[:63],
                "bucket": bucket[:63],
            },
        },
        "spec": {
            "ttlSecondsAfterFinished": JOB_TTL_SECONDS,
            "backoffLimit": 2,
            "template": {
                "metadata": {
                    "labels": {
                        "app": "cooking-clipper",
                        "component": "job",
                    },
                },
                "spec": {
                    "restartPolicy": "Never",
                    "containers": [
                        {
                            "name": "clipper",
                            "image": JOB_IMAGE,
                            "imagePullPolicy": JOB_IMAGE_PULL_POLICY,
                            "args": [s3_url],
                            "env": env,
                            "resources": {
                                "requests": {"cpu": "500m", "memory": "512Mi"},
                                "limits": {"cpu": "2", "memory": "2Gi"},
                            },
                        }
                    ],
                },
            },
        },
    }


def _get_active_jobs(batch_api, bucket: str) -> list[dict]:
    """Return jobs (running or pending) for the given bucket."""
    jobs = []
    try:
        resp = batch_api.list_namespaced_job(
            namespace=NAMESPACE,
            label_selector=f"app=cooking-clipper,component=job,bucket={bucket}",
        )
        for j in resp.items:
            status = "running"
            if j.status.succeeded and j.status.succeeded > 0:
                status = "succeeded"
            elif j.status.failed and j.status.failed > 0:
                status = "failed"
            elif j.status.active and j.status.active > 0:
                status = "running"
            jobs.append({
                "name": j.metadata.name,
                "video_key": j.metadata.labels.get("video-key", ""),
                "status": status,
                "created": j.metadata.creation_timestamp.isoformat(),
            })
    except ApiException as exc:
        log.warning("Failed to list jobs: %s", exc)
    return jobs


def _ensure_namespace(core_api):
    """Create the operator namespace if it doesn't exist."""
    try:
        core_api.read_namespace(NAMESPACE)
    except ApiException as exc:
        if exc.status == 404:
            log.info("Creating namespace %s", NAMESPACE)
            core_api.create_namespace({
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": NAMESPACE},
            })
        else:
            raise


# ── Flask App ───────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=None)


# ── API routes ──────────────────────────────────────────────────────────────


@app.route("/")
@app.route("/<path:path>")
def serve_frontend(path="index.html"):
    """Serve static frontend files."""
    frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
    requested = os.path.normpath("/" + path).lstrip("/")
    full_path = os.path.join(frontend_dir, requested)
    if not full_path.startswith(os.path.normpath(frontend_dir)):
        return jsonify({"error": "Forbidden"}), 403
    try:
        return send_from_directory(frontend_dir, requested)
    except Exception:
        return jsonify({"error": "Not found"}), 404


@app.route("/api/buckets")
def api_list_buckets():
    """List all S3 buckets (projects)."""
    s3 = _s3_client()
    buckets = _list_buckets(s3)
    return jsonify({"buckets": buckets})


@app.route("/api/buckets/<bucket>/videos")
def api_list_videos(bucket: str):
    """List videos in a bucket with processing status."""
    s3 = _s3_client()
    videos = _list_videos(s3, bucket)

    batch_api = client.BatchV1Api()
    active_jobs = {j["video_key"]: j for j in _get_active_jobs(batch_api, bucket)}

    for v in videos:
        key = v["key"]
        if key in active_jobs:
            v["status"] = active_jobs[key]["status"]
        elif _check_already_processed(s3, bucket, key):
            v["status"] = "done"
        else:
            v["status"] = "unprocessed"

        # Attach direct S3 HTTP URLs for video player + metadata
        v["video_url"] = _to_s3_http_url(bucket, key)
        v["processed_url"] = _to_s3_http_url(bucket, _output_key_for(key))
        v["scores_url"] = _to_s3_http_url(bucket, _scores_key_for(key))
        v["config_url"] = _to_s3_http_url(bucket, _config_key_for(key))

        # Inline config if available (used to populate slider defaults)
        config = _fetch_json_from_s3(s3, bucket, _config_key_for(key))
        v["config"] = config

    return jsonify({"videos": videos})


@app.route("/api/buckets/<bucket>/jobs")
def api_list_jobs(bucket: str):
    """List jobs for a bucket."""
    batch_api = client.BatchV1Api()
    jobs = _get_active_jobs(batch_api, bucket)
    return jsonify({"jobs": jobs})


@app.route("/api/buckets/<bucket>/process", methods=["POST"])
def api_process_video(bucket: str):
    """Trigger a Job to process a video.

    JSON body::
        {"key": "path/to/video.mp4",
         "clip_duration": 2.5,
         "motion_threshold": 0.15,
         "change_threshold": 20}
    """
    data = request.get_json(silent=True) or {}
    video_key = data.get("key", "")
    if not video_key:
        return jsonify({"error": "Missing 'key' in request body"}), 400

    s3 = _s3_client()

    # Verify the video exists
    try:
        s3.head_object(Bucket=bucket, Key=video_key)
    except Exception:
        return jsonify({"error": f"Video not found: s3://{bucket}/{video_key}"}), 404

    # Check if already processed
    if _check_already_processed(s3, bucket, video_key):
        return jsonify({"warning": "Already processed", "key": video_key}), 200

    # Build and create the Job
    manifest = _build_job_manifest(
        bucket,
        video_key,
        clip_duration=data.get("clip_duration"),
        motion_threshold=data.get("motion_threshold"),
        change_threshold=data.get("change_threshold"),
    )
    job_name = manifest["metadata"]["name"]
    batch_api = client.BatchV1Api()
    try:
        batch_api.create_namespaced_job(namespace=NAMESPACE, body=manifest)
        log.info("Created job %s for %s", job_name, video_key)
        return jsonify({"job": job_name, "key": video_key}), 201
    except ApiException as exc:
        if exc.status == 409:
            return jsonify({"info": "Job already exists", "job": job_name}), 200
        log.error("Failed to create job %s: %s", job_name, exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/status")
def api_status():
    """Health check."""
    return jsonify({"ok": True})


# ── CLI ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Cooking Clipper Operator — web UI + API",
    )
    parser.add_argument(
        "--kubeconfig",
        help="Path to kubeconfig (omit for in-cluster config)",
    )
    parser.add_argument(
        "--host",
        default=HOST,
        help=f"Bind address (default: {HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=PORT,
        help=f"Listen port (default: {PORT})",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable Flask debug mode",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(name)s • %(levelname)s • %(message)s",
    )

    log.info("Cooking Clipper Operator starting")
    log.info("  S3 Endpoint:  %s", S3_ENDPOINT)
    log.info("  Job Image:    %s", JOB_IMAGE)
    log.info("  Namespace:    %s", NAMESPACE)
    log.info("  Listening on:  %s:%d", args.host, args.port)

    # Load Kubernetes config
    if args.kubeconfig:
        config.load_kube_config(args.kubeconfig)
    else:
        config.load_incluster_config()

    core_api = client.CoreV1Api()
    _ensure_namespace(core_api)

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
