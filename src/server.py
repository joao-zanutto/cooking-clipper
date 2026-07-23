"""Local web server — serves the frontend & provides S3 routing info.

The frontend fetches **all** data directly from the S3-compatible endpoint
(SeaweedFS) via HTTP — CORS is supported.  This server only serves the static
HTML and exposes the S3 endpoint + URL structure so the frontend knows where
to find files.
"""

import argparse
import json
import logging
import os
import re
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

from .config import S3_ENDPOINT
from .storage import (
    build_s3_url,
    config_key_for,
    output_key_for,
    parse_s3_url,
    scores_key_for,
)

log = logging.getLogger("cooking-clipper")

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _to_http_url(s3_url: str) -> str:
    """Convert ``s3://bucket/key`` → ``S3_ENDPOINT/bucket/key``."""
    bucket, key = parse_s3_url(s3_url)
    base = S3_ENDPOINT.rstrip("/")
    return f"{base}/{bucket}/{key}"


# ── HTTP handler ────────────────────────────────────────────────────────────
class Handler(SimpleHTTPRequestHandler):
    """Serves the frontend and exposes S3 routing info via a script injection."""

    # Set by serve()
    s3_url: str = ""
    bucket: str = ""
    key: str = ""

    # ── Routing ──────────────────────────────────────────────────────────
    def do_GET(self):
        parsed = self.path.split("?")[0]

        if parsed == "/api/status":
            self._send_status()
        else:
            self._serve_page(parsed)

    # ── API: Status ──────────────────────────────────────────────────────
    def _send_status(self):
        """Return JSON with all URLs the frontend needs."""
        base = S3_ENDPOINT.rstrip("/")
        bucket = self.bucket
        key = self.key

        video_http = f"{base}/{bucket}/{key}"
        scores_http = f"{base}/{bucket}/{scores_key_for(key)}"
        config_http = f"{base}/{bucket}/{config_key_for(key)}"

        self._send_json({
            "ok": True,
            "s3_endpoint": S3_ENDPOINT,
            "bucket": bucket,
            "key": key,
            "video_url": video_http,
            "scores_url": scores_http,
            "config_url": config_http,
        })

    # ── Static pages ─────────────────────────────────────────────────────
    def _serve_page(self, path: str):
        if path == "" or path == "/":
            path = "/index.html"

        clean = os.path.normpath(path.lstrip("/"))
        if clean.startswith("..") or clean.startswith("/"):
            self._send_error(403, "Forbidden")
            return

        file_path = _FRONTEND_DIR / clean
        if not file_path.exists() or not file_path.is_file():
            self._send_error(404, "Not found")
            return

        mime = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json",
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }.get(file_path.suffix.lower(), "application/octet-stream")

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        # For index.html, inject bootstrap data
        if path in ("", "/", "/index.html"):
            self._write_with_bootstrap(file_path)
        else:
            with open(file_path, "rb") as f:
                self.wfile.write(f.read())

    def _write_with_bootstrap(self, file_path: Path):
        """Inject ``window.__COOKING_CLIPPER__`` into the HTML."""
        base = S3_ENDPOINT.rstrip("/")
        bucket = self.bucket
        key = self.key

        bootstrap = {
            "s3_endpoint": S3_ENDPOINT,
            "bucket": bucket,
            "key": key,
            "video_url": f"{base}/{bucket}/{key}",
            "scores_url": f"{base}/{bucket}/{scores_key_for(key)}",
            "config_url": f"{base}/{bucket}/{config_key_for(key)}",
        }

        html = file_path.read_text("utf-8")
        tag = '<script id="bootstrap-data" type="application/json">'
        inject = f'{tag}{json.dumps(bootstrap, separators=(",", ":"))}</script>'
        html = html.replace(tag, inject)
        self.wfile.write(html.encode("utf-8"))

    # ── Helpers ──────────────────────────────────────────────────────────
    def _send_json(self, data: dict):
        body = json.dumps(data, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, code: int, msg: str):
        body = json.dumps({"error": msg}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log.info(fmt, *args)


# ── CLI ─────────────────────────────────────────────────────────────────────
def serve(argv: list[str] | None = None) -> int:
    """Start the development viewer server.

    Usage::

        python -m src serve s3://bucket/path/video.mp4
    """
    parser = argparse.ArgumentParser(
        description="Cooking Clipper — motion viewer server",
    )
    parser.add_argument("s3_url", help="S3 URL of the original video")
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Local port (default: 8765)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s • %(message)s",
    )

    m = re.match(r"^s3://([^/]+)/(.+)$", args.s3_url)
    if not m:
        print("Error: invalid S3 URL — expected s3://bucket/key")
        return 1

    Handler.s3_url = args.s3_url
    Handler.bucket = m.group(1)
    Handler.key = m.group(2)

    scores_key = scores_key_for(Handler.key)
    config_key = config_key_for(Handler.key)
    output_key = output_key_for(Handler.key)

    base = S3_ENDPOINT.rstrip("/")

    print(f"  🎥  Cooking Clipper — Viewer")
    print(f"  ─────────────────────────────")
    print(f"  Open http://{args.host}:{args.port} in your browser")
    print(f"")
    print(f"  Original:  {base}/{Handler.bucket}/{Handler.key}")
    print(f"  Scores:    {base}/{Handler.bucket}/{scores_key}")
    print(f"  Config:    {base}/{Handler.bucket}/{config_key}")
    print(f"  Split:     {base}/{Handler.bucket}/{output_key}")
    print(f"")

    server = HTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    return 0


if __name__ == "__main__":
    sys.exit(serve())
