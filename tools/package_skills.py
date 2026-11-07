#!/usr/bin/env python3
"""Zip each skill for upload to Claude (Customize > Skills > Upload a skill).

    python tools/package_skills.py        # writes dist/<skill>.zip
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {"__pycache__", ".DS_Store", ".pytest_cache"}


def package(skill: Path, out_dir: Path) -> Path:
    out = out_dir / f"{skill.name}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(skill.rglob("*")):
            if f.is_file() and not SKIP & set(f.parts):
                z.write(f, Path(skill.name) / f.relative_to(skill))
    return out


def main() -> int:
    out_dir = ROOT / "dist"
    out_dir.mkdir(exist_ok=True)
    for skill in sorted((ROOT / "skills").iterdir()):
        if (skill / "SKILL.md").exists():
            print(f"packaged {package(skill, out_dir).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
