"""S3-compatible storage abstraction (SeaweedFS, MinIO, AWS S3, …)."""

import io
import json
import os
import re

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError, EndpointConnectionError

from .config import (
    S3_ACCESS_KEY_ID,
    S3_ENDPOINT,
    S3_REGION,
    S3_SECRET_ACCESS_KEY,
    S3_SPLIT_SUFFIX,
)

# ── URL helpers ─────────────────────────────────────────────────────────────
_S3_URL_RE = re.compile(r"^s3://([^/]+)/(.+)$")


def parse_s3_url(url: str) -> tuple[str, str]:
    """Split ``s3://bucket/key/path`` into ``(bucket, key)``."""
    m = _S3_URL_RE.match(url)
    if not m:
        raise ValueError(f"Invalid S3 URL — expected s3://bucket/key, got: {url}")
    return m.group(1), m.group(2)


def build_s3_url(bucket: str, key: str) -> str:
    """Reassemble a ``(bucket, key)`` pair into an S3 URL."""
    return f"s3://{bucket}/{key}"


def _prefix_key_for(key: str, prefix: str, ext: str = ".json") -> str:
    """Prepend *prefix* to the filename (flat key, no directory).

    SeaweedFS S3 API on port 8333 rejects PUT requests to any key that
    contains ``/``, so we use flat keys with a dash separator.
    """
    name, _ = os.path.splitext(key)
    new_name = f"{name}{ext}"
    return f"{prefix}-{new_name}"


def scores_key_for(key: str) -> str:
    """S3 key for the motion-scores JSON.

    ``videos/video.mp4`` → ``videos/_Score/video_scores.json``
    """
    return _prefix_key_for(key, "_Score", "_scores.json")


def config_key_for(key: str) -> str:
    """S3 key for the processing-config JSON.

    ``videos/video.mp4`` → ``videos/_Config/video_config.json``
    """
    return _prefix_key_for(key, "_Config", "_config.json")


def output_key_for(key: str) -> str:
    """Prepend ``S3_SPLIT_SUFFIX`` with a ``.mp4`` extension.

    The extracted clips are always re-encoded to H.264/AAC in an ``.mp4``
    container for universal playback compatibility.

    Example: ``IMG_0128.mov`` → ``_Split-IMG_0128.mp4``
    """
    name, _ = os.path.splitext(key)
    return f"{S3_SPLIT_SUFFIX}-{name}.mp4"


# 10 GB threshold — effectively disables multipart for any reasonable file.
# SeaweedFS (and some other S3-compatible stores) don't support multipart.
_SINGLE_PART_CONFIG = TransferConfig(
    multipart_threshold=10 * 1024 * 1024 * 1024,
    use_threads=False,
)


# ── Storage client ──────────────────────────────────────────────────────────
class S3Storage:
    """Thin wrapper around a ``boto3`` S3 client.

    Parameters
    ----------
    endpoint:
        Override the S3 endpoint URL (e.g. ``http://localhost:8333``).
        Defaults to the ``S3_ENDPOINT`` env var.
    """

    def __init__(self, endpoint: str | None = None):
        self._endpoint = endpoint or S3_ENDPOINT
        self._client = boto3.client(
            "s3",
            endpoint_url=self._endpoint,
            region_name=S3_REGION,
            aws_access_key_id=S3_ACCESS_KEY_ID or None,
            aws_secret_access_key=S3_SECRET_ACCESS_KEY or None,
            config=BotoConfig(
                connect_timeout=30,
                read_timeout=60,
                retries={"max_attempts": 3},
            ),
        )

    # ── Upload via transfer manager ──────────────────────────────────
    def _upload_bytes(
        self,
        data: bytes,
        bucket: str,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> None:
        """Upload *data* via ``upload_fileobj`` (same path as video upload).

        Uses the transfer manager instead of raw ``put_object`` because
        SeaweedFS returns ``InternalError`` on ``put_object`` when no
        ``ContentType`` is provided.
        """
        buf = io.BytesIO(data)
        self._client.upload_fileobj(
            buf,
            bucket,
            key,
            Config=_SINGLE_PART_CONFIG,
            ExtraArgs={"ContentType": content_type},
        )

    # ── Public API ──────────────────────────────────────────────────────
    def download(self, s3_url: str, local_path: str) -> str:
        """Download the object at *s3_url* to a local file.

        Returns *local_path* for chaining.
        """
        bucket, key = parse_s3_url(s3_url)
        endpoint = self._client.meta.endpoint_url
        print(f"    ↓ Downloading s3://{bucket}/{key}")
        try:
            self._client.download_file(bucket, key, local_path)
        except EndpointConnectionError as exc:
            print(f"    ✗ Cannot reach S3 endpoint: {endpoint}")
            print(f"      DNS lookup failed for hostname. Possible causes:")
            print(f"        • mDNS/Avahi not running or hostname not advertised")
            print(f"        • Wrong endpoint in .env (S3_ENDPOINT)")
            print(f"        • SeaweedFS server is down")
            raise
        return local_path

    def upload(self, local_path: str, s3_url: str) -> str:
        """Upload a local file to the S3 URL.

        Tries single-part upload first (via a very high multipart threshold).
        If that fails, falls back to the transfer manager with bytes.
        """
        bucket, key = parse_s3_url(s3_url)
        endpoint = self._client.meta.endpoint_url
        print(f"    ↑ Uploading  → s3://{bucket}/{key}")

        try:
            try:
                self._client.upload_file(
                    local_path, bucket, key, Config=_SINGLE_PART_CONFIG
                )
            except ClientError:
                print("    Multipart-style upload failed; retrying via upload_fileobj...")
                with open(local_path, "rb") as f:
                    self._upload_bytes(f.read(), bucket, key)
        except EndpointConnectionError as exc:
            print(f"    ✗ Cannot reach S3 endpoint: {endpoint}")
            print(f"      DNS lookup failed for hostname. Possible causes:")
            print(f"        • mDNS/Avahi not running or hostname not advertised")
            print(f"        • Wrong endpoint in .env (S3_ENDPOINT)")
            print(f"        • SeaweedFS server is down")
            raise

        return s3_url

    def upload_json(self, data: dict, s3_url: str) -> str:
        """Serialize *data* as JSON and upload via boto3 ``put_object``."""
        bucket, key = parse_s3_url(s3_url)
        body = json.dumps(data, separators=(",", ":")).encode("utf-8")
        print(f"    ↑ Uploading  → s3://{bucket}/{key}")
        self._client.put_object(Bucket=bucket, Key=key, Body=body)
        return s3_url
