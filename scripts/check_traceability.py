"""Fail CI when docs/brd-traceability.md names a test or module that does not exist."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
doc = (ROOT / "docs" / "brd-traceability.md").read_text()
missing: list[str] = []
for ref in sorted(
    set(re.findall(r"`((?:agentdossier|tests|config|schema|scripts|web|eval|\.github)/[^`]+)`", doc))
):
    path = ROOT / ref
    if not (path.exists() or (path.parent.exists() and any(path.parent.glob(path.name)))):
        missing.append(ref)
if missing:
    print("traceability: referenced paths missing:", *missing, sep="\n  ")
    sys.exit(1)
print(f"traceability: {len(set(re.findall(r'FR-[0-9]+', doc)))} requirements referenced, all paths exist")
