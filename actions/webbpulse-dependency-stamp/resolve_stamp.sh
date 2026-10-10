#!/usr/bin/env bash
set -euo pipefail

if [ "${STAMP_FRESH_DEPENDENCIES:-false}" = "true" ]; then
  if [ -z "${STAMP_RUN_ID:-}" ]; then
    echo "::error::fresh-dependencies was requested but run-id is empty, so the dependency layer cannot be keyed."
    exit 1
  fi
  STAMP="$STAMP_RUN_ID"
  echo "fresh-dependencies was requested, so the dependency layer rebuilds."
else
  if [ -z "${STAMP_DOMAIN_OWNER:-}" ]; then
    echo "::error::domain-owner is empty, so the newest ${STAMP_PACKAGE} version cannot be resolved."
    exit 1
  fi
  RAW="$(aws codeartifact list-package-versions \
    --domain "$STAMP_DOMAIN" \
    --domain-owner "$STAMP_DOMAIN_OWNER" \
    --repository "$STAMP_REPOSITORY" \
    --format pypi \
    --package "$STAMP_PACKAGE" \
    --status Published \
    --sort-by PUBLISHED_TIME \
    --query 'versions[0].version' \
    --output text \
    --no-paginate)"
  LINES="$(printf '%s\n' "$RAW" | sed '/^[[:space:]]*$/d' | wc -l | tr -d '[:space:]')"
  if [ "$LINES" -gt 1 ]; then
    echo "::error::CodeArtifact returned ${LINES} lines for the newest ${STAMP_PACKAGE} version, so the dependency layer cannot be keyed."
    printf '%s\n' "$RAW"
    exit 1
  fi
  STAMP="$(printf '%s\n' "$RAW" | sed '/^[[:space:]]*$/d' | head -n 1 | tr -d '[:space:]')"
  if [ -z "$STAMP" ] || [ "$STAMP" = "None" ]; then
    echo "::error::No Published ${STAMP_PACKAGE} version resolved from CodeArtifact, so the dependency layer cannot be keyed."
    exit 1
  fi
fi

echo "Dependency resolution stamp: ${STAMP}"
echo "dependency-stamp=${STAMP}" >> "$GITHUB_OUTPUT"
