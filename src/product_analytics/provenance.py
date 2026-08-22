from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(paths: Iterable[str | Path], root: str | Path) -> dict[str, object]:
    root_path = Path(root).resolve()
    artifacts = []
    for raw_path in sorted((Path(p).resolve() for p in paths), key=lambda p: str(p)):
        if not raw_path.is_file():
            raise FileNotFoundError(raw_path)
        artifacts.append(
            {
                "path": raw_path.relative_to(root_path).as_posix(),
                "bytes": raw_path.stat().st_size,
                "sha256": sha256_file(raw_path),
            }
        )
    return {"algorithm": "sha256", "artifact_count": len(artifacts), "artifacts": artifacts}


def write_manifest(paths: Iterable[str | Path], root: str | Path, output: str | Path) -> dict[str, object]:
    manifest = build_manifest(paths, root=root)
    Path(output).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def validate_manifest(manifest_path: str | Path, root: str | Path | None = None) -> list[str]:
    manifest_path = Path(manifest_path)
    base = Path(root) if root is not None else manifest_path.parent
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for artifact in payload.get("artifacts", []):
        path = base / artifact["path"]
        if not path.is_file():
            failures.append(f"missing:{artifact['path']}")
            continue
        if path.stat().st_size != int(artifact["bytes"]):
            failures.append(f"size:{artifact['path']}")
            continue
        if sha256_file(path) != artifact["sha256"]:
            failures.append(f"sha256:{artifact['path']}")
    return failures
