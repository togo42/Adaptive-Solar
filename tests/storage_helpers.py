"""Seed real private HA Store envelopes inside an isolated test config."""
import json
from pathlib import Path


def seed_store(store, payload):
    path = Path(store.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": store.version, "minor_version": store.minor_version,
                               "key": store.key, "data": payload}), encoding="utf-8")
