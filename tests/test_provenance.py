import json
from pathlib import Path

from product_analytics.provenance import sha256_file, validate_manifest, write_manifest


def test_manifest_detects_artifact_change(tmp_path: Path):
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("alpha\n", encoding="utf-8")
    manifest_path = tmp_path / "MANIFEST.json"
    manifest = write_manifest([artifact], root=tmp_path, output=manifest_path)

    assert manifest["artifact_count"] == 1
    assert manifest["artifacts"][0]["sha256"] == sha256_file(artifact)
    assert validate_manifest(manifest_path, root=tmp_path) == []

    artifact.write_text("beta\n", encoding="utf-8")
    assert validate_manifest(manifest_path, root=tmp_path) == ["size:artifact.txt"] or validate_manifest(
        manifest_path, root=tmp_path
    ) == ["sha256:artifact.txt"]


def test_manifest_is_machine_readable(tmp_path: Path):
    artifact = tmp_path / "x.csv"
    artifact.write_text("a\n1\n", encoding="utf-8")
    manifest_path = tmp_path / "MANIFEST.json"
    write_manifest([artifact], root=tmp_path, output=manifest_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["algorithm"] == "sha256"
    assert payload["artifacts"][0]["path"] == "x.csv"
