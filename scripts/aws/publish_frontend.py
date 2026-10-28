"""Publish reviewed frontend assets after Terraform apply, then smoke-test."""
import json
import math
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]


def verify_public_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {"project", "status", "records"} or payload["project"] != "EnergyDemo" or payload["status"] != "working":
        raise ValueError("Invalid public API contract")
    records = payload["records"]
    if not isinstance(records, list) or len(records) > 100:
        raise ValueError("Invalid public record list")
    sources = set()
    for record in records:
        if (not isinstance(record, dict) or set(record) != {"source", "production", "unit"}
                or not isinstance(record["source"], str) or not record["source"].strip()
                or record["source"] in sources or record["unit"] != "kWh"
                or isinstance(record["production"], bool) or not isinstance(record["production"], (int, float))
                or not math.isfinite(record["production"]) or not 0 <= record["production"] <= 1_000_000_000):
            raise ValueError("Public API contains invalid or unexpected/private fields")
        sources.add(record["source"])


def main():
    outputs = json.loads(subprocess.check_output([
        "terraform", "-chdir=infrastructure/terraform-aws", "output", "-json"
    ], cwd=ROOT, text=True))
    bucket = outputs["frontend_bucket"]["value"]
    distribution = outputs["cloudfront_distribution_id"]["value"]
    site = outputs["site_url"]["value"]
    # Upload hashed assets first, then the entry point. Never delete old assets
    # while cached HTML might still reference them.
    subprocess.run([
        "aws", "s3", "sync", str(ROOT / "artifacts/aws/frontend"), f"s3://{bucket}/",
        "--exclude", "index.html", "--cache-control", "public,max-age=31536000,immutable",
        "--only-show-errors", "--region", "eu-north-1",
    ], check=True)
    subprocess.run([
        "aws", "s3", "cp", str(ROOT / "artifacts/aws/frontend/index.html"), f"s3://{bucket}/index.html",
        "--content-type", "text/html", "--cache-control", "no-cache,max-age=0,must-revalidate",
        "--only-show-errors", "--region", "eu-north-1",
    ], check=True)
    invalidation = json.loads(subprocess.check_output([
        "aws", "cloudfront", "create-invalidation", "--distribution-id", distribution,
        "--paths", "/", "/index.html",
    ], text=True))["Invalidation"]["Id"]
    subprocess.run(["aws", "cloudfront", "wait", "invalidation-completed",
                    "--distribution-id", distribution, "--id", invalidation], check=True)
    for attempt in range(6):
        try:
            with urlopen(site, timeout=15) as response:
                if response.status != 200 or b'<div id="root">' not in response.read():
                    raise ValueError("Frontend smoke test failed")
            with urlopen(site + "/api/energy", timeout=15) as response:
                if response.status != 200:
                    raise ValueError("API smoke test failed")
                verify_public_payload(json.load(response))
            try:
                with urlopen(site + "/api/me/energy", timeout=15):
                    raise ValueError("Private API accepted an anonymous request")
            except HTTPError as error:
                if error.code not in (401, 403):
                    raise
            print("Frontend/public database API: HTTP 200 and valid public schema; private API rejects anonymous access.")
            print("Site:", site)
            return
        except (HTTPError, URLError, ValueError):
            if attempt == 5:
                raise
            time.sleep(10)


if __name__ == "__main__":
    main()
