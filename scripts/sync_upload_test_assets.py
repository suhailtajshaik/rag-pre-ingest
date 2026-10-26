"""Archive locally retained uploads as hash-deduplicated test assets."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import filetype

ROOT = Path(__file__).resolve().parents[1]


def sync() -> None:
    destination = ROOT / "tests/fixtures/user_samples"
    existing = {
        hashlib.sha256(p.read_bytes()).hexdigest(): p
        for p in destination.iterdir()
        if p.suffix in {".png", ".jpg", ".jpeg", ".pdf", ".docx", ".xlsx", ".tiff", ".webp"}
    }
    connection = sqlite3.connect(ROOT / "data/jobs.sqlite3")
    names = dict(connection.execute("select id,file_name from jobs"))
    connection.close()
    records = []
    for source in sorted((ROOT / "data/uploads").iterdir()):
        if not source.is_file():
            continue
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest not in existing:
            kind = filetype.guess(source)
            if kind is None:
                raise ValueError(f"Unknown upload type: {source.name}")
            target = destination / f"uploaded-{digest[:16]}.{kind.extension}"
            shutil.copyfile(source, target)
            existing[digest] = target
        records.append(
            {
                "original_name": names.get(source.name),
                "sha256": digest,
                "asset": existing[digest].name,
                "bytes": source.stat().st_size,
            }
        )
    (destination / "uploads-manifest.json").write_text(json.dumps(records, indent=2) + "\n")
    print(f"{len(records)} retained uploads mapped to test assets; no duplicate copies")


if __name__ == "__main__":
    sync()
