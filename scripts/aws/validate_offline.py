"""Validate isolated Terraform copies. Never read live backend/state or credentials."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AWS_", "TF_VAR_", "TF_CLI_ARGS"))}
    env.update(AWS_EC2_METADATA_DISABLED="true", CHECKPOINT_DISABLE="1")
    with tempfile.TemporaryDirectory(prefix="energy-admin-offline-") as directory:
        target = Path(directory)
        shutil.copytree(ROOT / "infrastructure/modules", target / "infrastructure/modules")
        (target / "artifacts/aws").mkdir(parents=True)
        shutil.copyfile(ROOT / "artifacts/aws/lambda.zip", target / "artifacts/aws/lambda.zip")
        for name in ["terraform-aws", "terraform-aws-bootstrap", "terraform-aws-auth"]:
            source, destination = ROOT / "infrastructure" / name, target / "infrastructure" / name
            destination.mkdir()
            for file in [*source.glob("*.tf"), source / ".terraform.lock.hcl"]:
                shutil.copyfile(file, destination / file.name)
            shutil.copytree(source / "tests", destination / "tests")
            # Reuse only provider binaries, never backend metadata from .terraform/.
            providers = source / ".terraform/providers"
            if providers.is_dir():
                (destination / ".terraform").mkdir()
                (destination / ".terraform/providers").symlink_to(providers)
            for command in [["init", "-backend=false", "-input=false", "-lockfile=readonly"],
                            ["validate", "-no-color"], ["test", "-no-color"]]:
                subprocess.run(["terraform", "-chdir=" + str(destination), *command], check=True, env=env)


if __name__ == "__main__":
    main()
