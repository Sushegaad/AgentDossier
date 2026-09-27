"""Validate built catalog files against the schemas (refresh gate)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent.parent
out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "data" / "catalog")
names = ["resource", "compliance_record", "policy", "enterprise_config", "catalog_index"]
schemas = {n: json.loads((ROOT / "schema" / f"{n}.schema.json").read_text()) for n in names}
registry = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas.values()])
problems = 0

index = json.loads((out / "index.json").read_text())
for err in Draft202012Validator(schemas["catalog_index"], registry=registry).iter_errors(index):
    problems += 1
    print("index.json:", err.message[:200])

validator = Draft202012Validator(schemas["resource"], registry=registry)
agents = sorted((out / "agents").glob("*.json"))
for path in agents:
    rec = json.loads(path.read_text())
    for err in validator.iter_errors(rec):
        problems += 1
        if problems <= 20:
            print(f"{path.name}: {err.message[:200]}")

ids = {r["id"] for r in index["records"]}
missing = [p.name for p in agents if p.stem not in ids]
if missing:
    problems += 1
    print("agents without index rows:", missing[:5])
print(f"validate_catalog: {len(index['records'])} index rows, {len(agents)} agent files, {problems} problems")
sys.exit(1 if problems else 0)
