"""Legacy shim — delegates to ``src.main``.

Usage
-----
    python split.py <video.mp4> [output.mp4]
    python split.py s3://bucket/path/video.mp4
"""

import sys

from src.main import main

sys.exit(main())
