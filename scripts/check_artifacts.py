"""Inspect built archives for required runtime assets and accidental local files."""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path, PurePosixPath


def check_names(names: list[str], *, wheel: bool) -> None:
    for name in names:
        parts = PurePosixPath(name).parts
        if any(
            part in {"keys", ".venv", "__pycache__", ".git", "article-assets"} for part in parts
        ):
            raise ValueError(f"Unexpected packaged file: {name}")
        if any(
            part == ".env" or part.startswith(".env.") and part != ".env.example" for part in parts
        ):
            raise ValueError(f"Unexpected environment file: {name}")
        if name.endswith((".pem", ".key", ".p12", ".pfx", ".pyc")):
            raise ValueError(f"Unexpected credential or bytecode: {name}")
    required_assets = ["src/agent/prompts/review_hunk_v1.txt", "src/demo.py"]
    if not wheel:
        required_assets += [
            "README.md",
            "docs/deployment.md",
            "docs/readiness-assessment.md",
            ".dockerignore",
            ".env.example",
            "uv.lock",
            "infra/Dockerfile",
        ]
    for required in required_assets:
        if not any(name == required or name.endswith("/" + required) for name in names):
            raise ValueError(f"Missing asset: {required}")
    if not any(PurePosixPath(name).name == "LICENSE" for name in names):
        raise ValueError("Missing license")
    if wheel and any(name.startswith(("tests/", "docs/", "evals/")) for name in names):
        raise ValueError("Wheel contains development-only files")


def main() -> None:
    wheels = list(Path("dist").glob("*.whl"))
    sources = list(Path("dist").glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Expected exactly one wheel and one source archive in dist/")
    with zipfile.ZipFile(wheels[0]) as archive:
        check_names(archive.namelist(), wheel=True)
    with tarfile.open(sources[0]) as archive:
        check_names(archive.getnames(), wheel=False)
    print("Wheel and source archive contents verified")


if __name__ == "__main__":
    main()
