#!/usr/bin/env bash
# One-shot release: optional bump version in config.yaml + commit, push branch, tag, push tag.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PUSH_BRANCH=1
DRY_RUN=0
VERSION=""

strip_leading_v() {
  local x="$1"
  x="${x#v}"
  x="${x#V}"
  printf '%s' "$x"
}

usage() {
  cat >&2 <<EOF
Usage:
  $0 [VERSION] [--dry-run] [--no-push-branch]
  $0 --version VER [--dry-run] [--no-push-branch]

  VERSION / --version   Write version into config.yaml, commit, then tag vVER and push.
                        Example: $0 1.0.4   or   $0 --version 1.0.4   or   $0 v1.0.4

  Default (no version): use existing version: in config.yaml (no file change).

  --no-push-branch      Skip pushing the current branch (only tag + push tag).
  --dry-run             Print steps only; no file writes, commits, pushes, or tags.
EOF
  exit 1
}

# Optional first argument: release number (1.0.4 or v1.0.4 — must contain a dot after the first digit group)
if [[ $# -ge 1 && "$1" != -* ]]; then
  if [[ "$1" =~ ^v?[0-9]+\.[0-9A-Za-z.+*-]+$ ]]; then
    VERSION="$1"
    shift
  fi
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      [[ $# -ge 2 ]] || usage
      VERSION="$2"
      shift 2
      ;;
    --dry-run) DRY_RUN=1; shift ;;
    --no-push-branch) PUSH_BRANCH=0; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1" >&2; usage ;;
  esac
done

if [[ -n "$VERSION" ]]; then
  VER_PLAIN="$(strip_leading_v "$VERSION")"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] Would set config.yaml version to: $VER_PLAIN"
    python3 "$ROOT/scripts/tag_from_config.py" --set-version "$VER_PLAIN" --dry-run
    TAG="v$VER_PLAIN"
    echo "[dry-run] Would: git add config.yaml && git commit -m \"Bump version to $VER_PLAIN\""
  else
    python3 "$ROOT/scripts/tag_from_config.py" --set-version "$VER_PLAIN"
    git add config.yaml
    git commit -m "Bump version to $VER_PLAIN"
    TAG="$(python3 "$ROOT/scripts/tag_from_config.py" --print-tag)"
  fi
else
  TAG="$(python3 "$ROOT/scripts/tag_from_config.py" --print-tag)"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] Using version from config.yaml → tag: $TAG"
  fi
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  if [[ "$PUSH_BRANCH" -eq 1 ]]; then
    echo "[dry-run] Would: git push origin $(git branch --show-current)"
  fi
  if [[ -n "${VERSION:-}" ]]; then
    echo "[dry-run] Would create annotated git tag: $TAG"
  else
    python3 "$ROOT/scripts/tag_from_config.py" --dry-run
  fi
  echo "[dry-run] Would: git push origin $TAG"
  exit 0
fi

if [[ "$PUSH_BRANCH" -eq 1 ]]; then
  BRANCH="$(git branch --show-current)"
  echo "[INFO] Pushing branch: $BRANCH"
  git push origin "$BRANCH"
fi

echo "[INFO] Creating tag $TAG from config.yaml"
python3 "$ROOT/scripts/tag_from_config.py"

echo "[INFO] Pushing tag: $TAG"
git push origin "$TAG"

echo "[INFO] Done. Release $TAG is on origin."
