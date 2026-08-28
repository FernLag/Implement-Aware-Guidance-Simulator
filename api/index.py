"""Vercel entry point.

Vercel looks for a WSGI or ASGI callable named `app` in this module. The Flask
application is created once per cold start and reused for the life of that
instance.

Read the caveats in DEPLOYMENT.md before using this. Two of them matter:
the filesystem is read only apart from /tmp, so contact messages need
AGGSIM_MESSAGE_STORE pointed somewhere durable or the form disables itself;
and the in-process rate limiter cannot see other instances, so it stops being
a meaningful control.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Serverless instances are short lived and numerous, so the per-process token
# bucket resets constantly. Tighten it rather than leaving a limit that reads
# as protection but is not.
os.environ.setdefault("AGGSIM_RATE_LIMIT_PER_MINUTE", "30")
os.environ.setdefault("AGGSIM_RATE_LIMIT_BURST", "10")
# Function timeout is the binding constraint, not our own step cap.
os.environ.setdefault("AGGSIM_MAX_SIMULATION_STEPS", "12000")

from web.app import create_app  # noqa: E402

app = create_app()
