#!/usr/bin/env bash
# Create a zip archive of the current repository at HEAD,
# excluding .gitlab-ci.yml. The archive is saved to ./zip
# with the pattern <repo-name>-<commit-hash>.zip.

set -euo pipefail

REPO_NAME=$(basename "$(pwd)")
COMMIT_HASH=$(git rev-parse --short HEAD)
OUTPUT="zip/${REPO_NAME}-${COMMIT_HASH}.zip"

mkdir -p ./zip

git archive \
  --format=zip \
  --output="$OUTPUT" \
  HEAD \
  . \
  ':(exclude).gitlab-ci.yml'

echo "Output: $OUTPUT"