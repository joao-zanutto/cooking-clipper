"""S3-compatible storage abstraction (SeaweedFS, MinIO, AWS S3, …)."""

import os
import re

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

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


def output_key_for(key: str) -> str:
    """Insert ``S3_SPLIT_SUFFIX`` as a parent folder.

    Example: ``videos/video.mp4`` → ``videos/_Split/video.mp4``
    """
    folder, filename = os.path.split(key)
    if folder:
        return f"{folder}/{S3_SPLIT_SUFFIX}/{filename}"
    return f"{S3_SPLIT_SUFFIX}/{filename}"


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
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint or S3_ENDPOINT,
            region_name=S3_REGION,
            aws_access_key_id=S3_ACCESS_KEY_ID or None,
            aws_secret_access_key=S3_SECRET_ACCESS_KEY or None,
            config=BotoConfig(
                connect_timeout=30,
                read_timeout=60,
                retries={"max_attempts": 3},
            ),
        )

    def download(self, s3_url: str, local_path: str) -> str:
        """Download the object at *s3_url* to a local file.

        Returns *local_path* for chaining.
        """
        bucket, key = parse_s3_url(s3_url)
        print(f"    ↓ Downloading s3://{bucket}/{key}")
        self._client.download_file(bucket, key, local_path)
        return local_path

    def upload(self, local_path: str, s3_url: str) -> str:
        """Upload a local file to the S3 URL.

        Tries single-part upload first (via a very high multipart threshold).
        If that fails, falls back to a direct ``put_object`` call.
        """
        bucket, key = parse_s3_url(s3_url)
        print(f"    ↑ Uploading  → s3://{bucket}/{key}")

        try:
            self._client.upload_file(
                local_path, bucket, key, Config=_SINGLE_PART_CONFIG
            )
        except ClientError:
            print("    Multipart-style upload failed; retrying with single PUT...")
            with open(local_path, "rb") as f:
                self._client.put_object(Bucket=bucket, Key=key, Body=f)

        return s3_url
