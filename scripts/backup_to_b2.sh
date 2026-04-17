#!/usr/bin/env bash
# Back up data/ and analysis/ to a Backblaze B2 bucket as a timestamped
# tar.zst archive. One full dump per run — no incremental — because solid
# zstd compression keeps the archive a small fraction of the raw ~1.2 GB
# data tree, so full dumps are cheap and versioning comes for free (each
# archive is its own point-in-time).
#
# Setup (once):
#   rclone config                       # create a 'b2' remote of type 'b2'
#   export JUDEX_B2_BUCKET=my-bucket    # or accept the default below
#
# Env vars:
#   JUDEX_B2_REMOTE   rclone remote name   (default: b2)
#   JUDEX_B2_BUCKET   B2 bucket name       (default: judex-curia)

set -euo pipefail

REMOTE="${JUDEX_B2_REMOTE:-b2}"
BUCKET="${JUDEX_B2_BUCKET:-judex-curia}"
SOURCES=(data analysis)
DRY_RUN=0

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
  cat <<EOF

Usage: scripts/backup_to_b2.sh [--dry-run]

  --dry-run   Build the archive locally, print its size, skip the upload.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; usage; exit 1 ;;
  esac
done

for cmd in rclone tar zstd; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "missing dependency: $cmd" >&2
    exit 1
  fi
done

if ! rclone listremotes | grep -q "^${REMOTE}:$"; then
  echo "no rclone remote named '${REMOTE}'. run 'rclone config' first." >&2
  exit 1
fi

missing=()
for src in "${SOURCES[@]}"; do
  [[ -d "$src" ]] || missing+=("$src")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "missing source dirs: ${missing[*]}" >&2
  exit 1
fi

stamp=$(date -u +%Y-%m-%dT%H%M%SZ)
archive=$(mktemp --suffix=".tar.zst" -t "judex-backup-${stamp}.XXXX")
trap 'rm -f "$archive"' EXIT

echo ">>> archiving: ${SOURCES[*]}"
tar \
  --exclude='__pycache__' \
  --exclude='__marimo__' \
  --exclude='*.pyc' \
  -I 'zstd -19 --threads=0' \
  -cf "$archive" \
  "${SOURCES[@]}"

size=$(du -h "$archive" | cut -f1)
echo ">>> archive built: ${size}"

if [[ $DRY_RUN -eq 1 ]]; then
  echo ">>> dry-run: skipping upload. archive at: ${archive}"
  trap - EXIT  # keep the file so you can inspect it
  exit 0
fi

dest="${REMOTE}:${BUCKET}/backups/judex-backup-${stamp}.tar.zst"
echo ">>> uploading -> ${dest}"
rclone copyto --progress "$archive" "$dest"
echo "done."
