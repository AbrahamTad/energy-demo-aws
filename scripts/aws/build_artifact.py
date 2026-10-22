"""Package only the sample Lambda and AWS-mode frontend; no AWS calls."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    output = ROOT / "artifacts/aws"
    output.mkdir(parents=True, exist_ok=True)
    frontend = output / "frontend"
    if frontend.exists():
        assert frontend.resolve().is_relative_to((ROOT / "artifacts/aws").resolve())
        shutil.rmtree(frontend)
    shutil.copytree(ROOT / "frontend/dist", frontend)
    assert (frontend / "index.html").is_file()
    with zipfile.ZipFile(output / "lambda.zip", "w") as archive:
        info = zipfile.ZipInfo("handler.py", (1980, 1, 1, 0, 0, 0))
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        archive.writestr(info, (ROOT / "lambda/energy/handler.py").read_bytes())
    sha = os.environ.get("GITHUB_SHA") or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    files = [output / "lambda.zip", *sorted(frontend.rglob("*"))]
    hashes = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in files if p.is_file()}
    (output / "manifest.json").write_text(json.dumps({"commit": sha, "sha256": hashes}, indent=2) + "\n")
    print(f"Packaged sample Lambda and {len(hashes) - 1} frontend files for commit {sha}.")


if __name__ == "__main__":
    main()
