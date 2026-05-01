from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from .schemas import GenerationResult


def write_manifest(output_dir: Path, result: GenerationResult) -> Path:
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return manifest_path


def zip_run(run_root: Path, run_id: UUID) -> Path:
    zip_path = run_root / f"{run_id}.zip"
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        for file in run_root.rglob("*"):
            if file == zip_path or file.is_dir():
                continue
            archive.write(file, file.relative_to(run_root))
    return zip_path
