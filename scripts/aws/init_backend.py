"""OIDC-only guarded backend initialization. Called only by manual deployment."""
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def configuration(account):
    if not re.fullmatch(r"[0-9]{12}", account) or account == "000000000000":
        raise ValueError("A real AWS account ID is required")
    return {
        "bucket": f"energy-demo-tfstate-{account}-eu-north-1",
        "key": "energy-demo/aws/terraform.tfstate",
        "region": "eu-north-1", "encrypt": True, "use_lockfile": True,
        "allowed_account_ids": [account],
    }


def main():
    account = os.environ.get("TF_VAR_account_id", "")
    backend = configuration(account)
    if any(k.startswith("AWS_ENDPOINT_URL") for k in os.environ):
        raise SystemExit("AWS endpoint overrides are forbidden")
    if (not os.environ.get("AWS_SESSION_TOKEN")
            or not os.environ.get("AWS_ACCESS_KEY_ID", "").startswith("ASIA")):
        raise SystemExit("Only temporary OIDC credentials are accepted")
    identity = json.loads(subprocess.check_output(["aws", "sts", "get-caller-identity", "--region", "eu-north-1"], text=True))
    if identity["Account"] != account:
        raise SystemExit("AWS account mismatch")
    directory = ROOT / "infrastructure/terraform-aws"
    args = ["terraform", f"-chdir={directory}", "init", "-input=false", "-lockfile=readonly"]
    for key, value in backend.items():
        encoded = json.dumps(value) if not isinstance(value, str) else value
        args.append(f"-backend-config={key}={encoded}")
    subprocess.run(args, check=True)


if __name__ == "__main__":
    main()
