"""Deterministic Lambda code/dependencies and AWS frontend; no AWS calls."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
APP_FILES = ["handler.py", "user_handler.py", "energy_auth.py", "energy_store.py", "energy_validation.py"]


def main():
    output = ROOT / "artifacts/aws"
    output.mkdir(parents=True, exist_ok=True)
    frontend = output / "frontend"
    if frontend.exists():
        assert frontend.resolve().is_relative_to((ROOT / "artifacts/aws").resolve())
        shutil.rmtree(frontend)
    shutil.copytree(ROOT / "frontend/dist", frontend)
    assert (frontend / "index.html").is_file()
    with tempfile.TemporaryDirectory(prefix="energy-lambda-") as temporary:
        vendor = Path(temporary)
        subprocess.run([
            sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-compile",
            "--require-hashes", "--only-binary=:all:", "--implementation", "cp",
            "--python-version", "3.12", "--abi", "cp312", "--abi", "abi3", "--abi", "none",
            "--platform", "manylinux_2_34_x86_64", "--platform", "manylinux_2_28_x86_64",
            "--platform", "manylinux2014_x86_64", "--target", str(vendor),
            "-r", str(ROOT / "lambda/energy/requirements-lambda.txt"),
        ], check=True)
        for name in APP_FILES:
            shutil.copyfile(ROOT / "lambda/energy" / name, vendor / name)
        with zipfile.ZipFile(output / "lambda.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(vendor.rglob("*")):
                if (not file.is_file() or "__pycache__" in file.parts or file.suffix == ".pyc"
                        or file.relative_to(vendor).parts[0] == "bin"):
                    continue
                info = zipfile.ZipInfo(file.relative_to(vendor).as_posix(), (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, file.read_bytes())
    sha = os.environ.get("GITHUB_SHA") or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    files = [output / "lambda.zip", *sorted(frontend.rglob("*"))]
    hashes = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in files if p.is_file()}
    (output / "manifest.json").write_text(json.dumps({"commit": sha, "sha256": hashes}, indent=2) + "\n")
    print(f"Packaged energy Lambda handlers and {len(hashes) - 1} frontend files for commit {sha}.")


if __name__ == "__main__":
    main()
