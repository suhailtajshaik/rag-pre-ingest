"""Expose setuptools' package mapping to mypy without duplicating source files."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="rag-typecheck-") as directory:
    (Path(directory) / "rag_pre_ingest").symlink_to(root / "src", target_is_directory=True)
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "-p", "rag_pre_ingest"],
        cwd=root,
        env={**os.environ, "MYPYPATH": directory},
        check=False,
    )
raise SystemExit(result.returncode)
