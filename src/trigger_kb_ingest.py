"""Trigger knowledge base ingestion by pushing an event to Hatchet.

Usage:
    just ingest path/to/document.pdf

This pushes a kb:ingest event to Hatchet, which triggers the
knowledge_ingestion workflow.
"""

import sys
from pathlib import Path

from hatchet_sdk import Hatchet

hatchet = Hatchet()

file_path = Path(sys.argv[1]).resolve()
if not file_path.exists():
    print(f"Error: file not found: {file_path}")
    sys.exit(1)

event_payload = {
    "file_path": str(file_path),
    "source": "cli_trigger",
}

hatchet.event.push("kb:ingest", event_payload)
print(f"Pushed kb:ingest event for {file_path}")
print("Check Hatchet dashboard for workflow run status.")
