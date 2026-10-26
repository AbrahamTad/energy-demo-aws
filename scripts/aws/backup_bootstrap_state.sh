#!/usr/bin/env bash
set -euo pipefail
umask 077

SOURCE="$HOME/projects/aws-learning/energy-demo/.local/terraform-aws-bootstrap.tfstate"
BACKUP_DIR="$HOME/aws-secure-backups/energy-demo"

if [[ ! -s "$SOURCE" ]]; then
  echo "No Terraform bootstrap state found. Backup skipped."
  exit 1
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$BACKUP_DIR/terraform-aws-bootstrap-$TIMESTAMP.tfstate"

cp --update=none-fail -- "$SOURCE" "$BACKUP"
chmod 600 "$BACKUP"

echo "Local state backup created."
ls -l "$BACKUP"
