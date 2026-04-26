#!/usr/bin/env bash
# Back up to a Backblaze B2 bucket in two parts:
#
#   1. data/raw/ is additively synced (rclone copy, never --delete) to
#      <bucket>/raw/. Files are mostly immutable — peça bytes are
#      content-addressed by sha1(url), HTML fragments live under
#      raw/html/<CLASSE>_<N>.tar.gz and are only rewritten on re-scrape —
#      so after the first ~8 GB run, each subsequent sync moves only
#      newly scraped bytes. Enable B2 bucket versioning + a lifecycle
#      rule on the bucket for history; the script never passes --delete,
#      so it won't remove remote-only files itself.
#
#   2. data/source/ + analysis/ are tar+zstd'd into a timestamped
#      snapshot at <bucket>/snapshots/judex-snapshot-<stamp>.tar.zst.
#      These are plain JSON/text, compress well, and benefit from being a
#      coherent point-in-time artifact. Cheap enough to keep many versions.
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
DRY_RUN=0

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
  cat <<EOF

Usage: scripts/backup_to_b2.sh [--dry-run]

  --dry-run   List what rclone would copy; build the snapshot locally; skip all uploads.
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

for src in data/raw data/source analysis; do
  [[ -d "$src" ]] || { echo "missing source dir: $src" >&2; exit 1; }
done

stamp=$(date -u +%Y-%m-%dT%H%M%SZ)

# ---------- part 1: additive sync of data/cache ----------
echo ">>> syncing data/raw -> ${REMOTE}:${BUCKET}/raw"
copy_args=(
  --transfers 16
  --checkers 32
  --fast-list
  --progress
  --exclude '__pycache__/**'
  --exclude '**/*.pyc'
)
if [[ $DRY_RUN -eq 1 ]]; then
  copy_args+=(--dry-run)
fi
rclone copy "${copy_args[@]}" data/raw "${REMOTE}:${BUCKET}/raw"

# ---------- part 2: timestamped snapshot of data/source + analysis ----------
archive=$(mktemp --suffix=".tar.zst" -t "judex-snapshot-${stamp}.XXXX")
trap 'rm -f "$archive"' EXIT

echo ">>> archiving: data/source analysis"
tar \
  --exclude='__pycache__' \
  --exclude='__marimo__' \
  --exclude='*.pyc' \
  -I 'zstd -19 --threads=0' \
  -cf "$archive" \
  data/source analysis

size=$(du -h "$archive" | cut -f1)
echo ">>> snapshot built: ${size}"

if [[ $DRY_RUN -eq 1 ]]; then
  echo ">>> dry-run: skipping upload. snapshot at: ${archive}"
  trap - EXIT  # keep the file so you can inspect it
  exit 0
fi

dest="${REMOTE}:${BUCKET}/snapshots/judex-snapshot-${stamp}.tar.zst"
echo ">>> uploading -> ${dest}"
rclone copyto --progress "$archive" "$dest"
echo "done."
