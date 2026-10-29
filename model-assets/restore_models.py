#!/usr/bin/env python3
"""Reassemble the GitHub-safe Base64 model parts and verify their SHA-256."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CHUNKS = ROOT / "chunks"
DEST = ROOT / "rk3588-yolo11n"
MODELS = {
    "visdrone-yolo11n-int8-640-rk3588.rknn": (
        22,
        "79a3047684f14c55c3b5c875a7701f71b12aaccc3187ed3cd1d277492f35df3a",
    ),
    "visdrone-yolo11n-fp16-640-rk3588.rknn": (
        36,
        "d6ebc76ac8715310375fe77f598a9a74f6d3ba8980257711551d39299de499f9",
    ),
}


def restore(name: str, part_count: int, expected_sha256: str) -> None:
    prefix = f"{name}.b64.part"
    target = DEST / name
    temporary = target.with_suffix(target.suffix + ".tmp")
    digest = hashlib.sha256()
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        with temporary.open("wb") as output:
            for index in range(part_count):
                part = CHUNKS / f"{prefix}{index:03d}"
                encoded = part.read_bytes()
                decoded = base64.b64decode(encoded, validate=True)
                output.write(decoded)
                digest.update(decoded)

        actual = digest.hexdigest()
        if actual != expected_sha256:
            raise ValueError(f"SHA-256 mismatch for {name}: {actual}")
        temporary.replace(target)
        print(f"OK {target.relative_to(ROOT.parent)}  sha256={actual}")
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    for name, (part_count, expected_sha256) in MODELS.items():
        restore(name, part_count, expected_sha256)


if __name__ == "__main__":
    main()
