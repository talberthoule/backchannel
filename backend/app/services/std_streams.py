"""Guarantee sys.stdout and sys.stderr are writable objects.

A PyInstaller bundle built with console=False has no console, so Python leaves
both as None. Libraries write to them anyway and raise AttributeError on
None.write, and not all of them unwind cleanly: tqdm takes its process-global
write lock, touches the stream, and releases only on the next line, so the
exception escapes with the lock held and every later progress bar in the
process deadlocks (ALP-373).

The desktop launcher calls this first thing, before it imports anything else.
It is called again when the download machinery loads, because the backend
should not depend on which entry point started it -- Docker, `uvicorn` in a
dev shell and the frozen launcher all reach the same code.
"""

from __future__ import annotations

import os
import sys


def ensure() -> None:
    """Replace None streams with a discard sink. Real streams are left alone."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8", errors="replace"))
            except OSError:  # pragma: no cover - no devnull is not survivable anyway
                continue
        # Libraries fall back to __stdout__/__stderr__ when the main pair looks odd.
        if getattr(sys, f"__{name}__", None) is None:
            setattr(sys, f"__{name}__", getattr(sys, name))
