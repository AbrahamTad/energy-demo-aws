"""Prepare one reviewed DLQ message for recovery, locally. Never calls AWS or sends mail."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lambda/energy"))
from contact_events import recovery_payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["sns", "lambda"], required=True)
    parser.add_argument("--input", type=Path, required=True, help="File containing one decoded SQS Body")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--topic-arn", required=True)
    parser.add_argument("--configuration-set", required=True)
    args = parser.parse_args()
    os.environ.update(CONTACT_TOPIC_ARN=args.topic_arn, CONTACT_SES_CONFIG=args.configuration_set)
    try:
        payload = recovery_payload(json.loads(args.input.read_text()), args.source)
    except Exception:
        parser.exit(2, "Invalid recovery input. No payload written.\n")
    # Exclusive creation and restrictive permissions: SES event metadata can contain PII.
    with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(payload, stream)
    print("Recovery payload prepared locally. No AWS calls made.")


if __name__ == "__main__":
    main()
