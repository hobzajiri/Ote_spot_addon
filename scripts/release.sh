#!/usr/bin/env bash
# One-shot release: optional push of current branch, git tag from config.yaml, push tag.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PUSH_BRANCH=1
DRY_RUN=0

usage() {
  echo "Usage: $0 [--dry-run] [--no-push-branch]" >&2
  echo "  Default: git push current branch, create annotated tag v{version} from config.yaml, git push tag." >&2
  echo "  --no-push-branch  Only create tag and push the tag (use when branch is already on origin)." >&2
  echo "  --dry-run         Show what would happen; no git push, no tag created." >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --no-push-branch) PUSH_BRANCH=0; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1" >&2; usage ;;
  esac
done

TAG="$(python3 "$ROOT/scripts/tag_from_config.py" --print-tag)"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] Would read version from config.yaml → tag: $TAG"
  if [[ "$PUSH_BRANCH" -eq 1 ]]; then
    echo "[dry-run] Would: git push origin $(git branch --show-current)"
  fi
  python3 "$ROOT/scripts/tag_from_config.py" --dry-run
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
