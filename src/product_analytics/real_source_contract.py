from __future__ import annotations

from hashlib import sha256
from pathlib import Path

UCI_ONLINE_RETAIL_II_ARCHIVE_SHA256 = (
    "572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb"
)
UCI_ONLINE_RETAIL_II_ARCHIVE_BYTES = 45_622_418
UCI_ONLINE_RETAIL_II_WORKBOOK_SHA256 = (
    "bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980"
)
UCI_ONLINE_RETAIL_II_WORKBOOK_BYTES = 45_622_278


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_official_source_archive(path: Path) -> None:
    if path.stat().st_size != UCI_ONLINE_RETAIL_II_ARCHIVE_BYTES:
        raise RuntimeError(
            "UCI Online Retail II archive size changed: "
            f"expected {UCI_ONLINE_RETAIL_II_ARCHIVE_BYTES}, got {path.stat().st_size}"
        )
    observed = sha256_file(path)
    if observed != UCI_ONLINE_RETAIL_II_ARCHIVE_SHA256:
        raise RuntimeError(
            "UCI Online Retail II archive SHA-256 changed: "
            f"expected {UCI_ONLINE_RETAIL_II_ARCHIVE_SHA256}, got {observed}. "
            "Review the upstream source before accepting new evidence."
        )


def assert_official_workbook(path: Path) -> None:
    if path.stat().st_size != UCI_ONLINE_RETAIL_II_WORKBOOK_BYTES:
        raise RuntimeError(
            "UCI Online Retail II workbook size changed: "
            f"expected {UCI_ONLINE_RETAIL_II_WORKBOOK_BYTES}, got {path.stat().st_size}"
        )
    observed = sha256_file(path)
    if observed != UCI_ONLINE_RETAIL_II_WORKBOOK_SHA256:
        raise RuntimeError(
            "UCI Online Retail II workbook SHA-256 changed: "
            f"expected {UCI_ONLINE_RETAIL_II_WORKBOOK_SHA256}, got {observed}. "
            "Review the upstream source before accepting new evidence."
        )
