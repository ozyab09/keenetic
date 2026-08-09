"""Utility for working with a Keenetic router via REST API (NDMS RCI).

Workflow:
  1. Authentication
  2. Select a host from the client list
  3. Interactive mode and port selection
  4. Run

Modes:
  1. Collect — 5 API requests every 5 s, aggregates remote hosts
  2. Snapshot — one-shot view of active connections

Dependencies: Python standard library only.
"""

from keenetic.cli import main

__all__ = ["main"]
