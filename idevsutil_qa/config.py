from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Build


def load_builds(json_path: str) -> dict[str, Build]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: Build(**v) for k, v in data.items()}


def load_files(files_path: str) -> list[str]:
    with open(files_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.items()


def getFilePaths(run_dir: Path, filenames: list[str], source: str) -> list[Path]:
    files: list[Path] = []
    for filename in filenames:
        if os.name == "nt":
            parts = filename.split("\\")
            if len(parts) == 1:
                # files.append(run_dir / "source" / filename)
                files.append(run_dir / source / filename)

            else:
                # path = run_dir.joinpath("source")
                path = run_dir.joinpath(source)
                for p in parts[1:]:
                    path = path.joinpath(p)
                files.append(path)
        else:
            # files.append(run_dir / "source" / filename)
            files.append(run_dir / source / filename)

    return files
