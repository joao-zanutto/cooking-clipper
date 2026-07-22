"""Allow ``python -m src`` to invoke ``src.main.main()``."""

import sys

from .main import main

sys.exit(main())
