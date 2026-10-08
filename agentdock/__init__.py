"""AgentDock: a local, review-first workbench for coding agents."""

__version__ = "0.3.0"

import sys

if sys.version_info < (3, 11):
    raise RuntimeError("AgentDock requires Python 3.11 or newer.")
