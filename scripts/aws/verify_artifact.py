"""Validate same-commit artifacts before any AWS authentication."""
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def verify(output, expected_commit):
    manifest = json.loads((output / "manifest.json").read_text())
    if manifest["commit"] != expected_commit:
        raise ValueError("Build artifact belongs to a different commit")
    actual = {p.relative_to(output).as_posix() for p in output.rglob("*")
              if p.is_file() and p.name != "manifest.json"}
    if actual != set(manifest["sha256"]):
        raise ValueError("Unexpected or missing artifact files")
    for name, digest in manifest["sha256"].items():
        path = output / name
        if (not path.resolve().is_relative_to(output.resolve()) or path.is_symlink()
                or (name != "lambda.zip" and not name.startswith("frontend/"))):
            raise ValueError("Invalid artifact path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Artifact checksum mismatch")
    with zipfile.ZipFile(output / "lambda.zip") as archive:
        required = {"handler.py", "user_handler.py", "energy_auth.py", "energy_store.py", "energy_validation.py",
                    "jwt/__init__.py", "cryptography/__init__.py"}
        names = archive.namelist()
        allowed = re.compile(r"(?:jwt|cryptography|cffi|pycparser)/|(?:pyjwt|cryptography|cffi|pycparser)-[0-9][^/]*\.dist-info/|_cffi_backend\.[^/]+\.so$")
        apps = {"handler.py", "user_handler.py", "energy_auth.py", "energy_store.py", "energy_validation.py"}
        if not required.issubset(names) or len(names) != len(set(names)) or archive.testzip():
            raise ValueError("Invalid energy Lambda ZIP")
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in info.filename
                    or (info.external_attr >> 16) & 0o170000 == 0o120000
                    or (info.filename not in apps and not allowed.match(info.filename))):
                raise ValueError("Unexpected Lambda archive path")
        if sum(info.file_size for info in archive.infolist()) > 200_000_000:
            raise ValueError("Lambda archive is too large")
    if not (output / "frontend/index.html").is_file():
        raise ValueError("Missing frontend entry point")


if __name__ == "__main__":
    sha = os.environ.get("GITHUB_SHA") or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    verify(ROOT / "artifacts/aws", sha)
    print("Build commit, checksums and ZIP contents verified.")
