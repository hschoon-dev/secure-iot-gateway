#!/bin/bash
set -euo pipefail

# Configuration
NFS_BASE="/data/nfs"
REPO_NAME="secure-iot-gateway"
REPO_URL="https://hschoon-dev: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@github.com/hschoon-dev/secure-iot-gateway.git"
BRANCH="active-dev"

REPO_DIR="$NFS_BASE/$REPO_NAME"

UPDATED=false

# Clone or update repo
if [ -d "$REPO_DIR/.git" ]; then
  echo "Repository for the SIoT-Gateway exists. Checking for updates..."

  cd "$REPO_DIR"

  git fetch origin "$BRANCH"

  LOCAL_HASH=$(git rev-parse "$BRANCH")
  REMOTE_HASH=$(git rev-parse "origin/$BRANCH")

  if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
    echo "Repository is already up to date."
  else
    echo "Updates detected. Pulling latest changes..."
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
    UPDATED=true
  fi
else
  echo "Repository not found. Cloning..."
  cd "$NFS_BASE"
  git clone --branch "$BRANCH" --single-branch "$REPO_URL"
  UPDATED=true
fi

# Copy partitions only if repo changed
if [ "$UPDATED" = true ]; then
  echo "Updating SIoT-Gateway partitions..."

  # Mapping: target -> list of repo items to copy
  declare -A TARGET_ITEMS=(
    ["$NFS_BASE/elinos-1/src"]="elinos-setup interface-partition LICENSE"
    ["$NFS_BASE/elinos-2/src"]="elinos-setup psmo-partition LICENSE"
    ["$NFS_BASE/elinos-3/src"]="elinos-setup cpc-partition LICENSE"
    ["$NFS_BASE/elinos-4/src"]="elinos-setup intermediate-vor-partition LICENSE"
    ["$NFS_BASE/elinos-5/src"]="elinos-setup intermediate-vor-partition-cpc LICENSE"
  )

  for TARGET in "${!TARGET_ITEMS[@]}"; do
    echo "Processing target: $TARGET"
    mkdir -p "$TARGET"

    for ITEM in ${TARGET_ITEMS["$TARGET"]}; do
      SRC_PATH="$REPO_DIR/$ITEM"
      DEST_PATH="$TARGET/$ITEM"

      if [ ! -e "$SRC_PATH" ]; then
        echo "  ERROR: Source not found: $SRC_PATH" >&2
        exit 1
      fi

      if [ -d "$SRC_PATH" ]; then
        echo "  Replacing directory $DEST_PATH"
        rm -rf "$DEST_PATH"
        cp -r "$SRC_PATH" "$DEST_PATH"
      else
        echo "  Replacing file $DEST_PATH"
        rm -f "$DEST_PATH"
        cp "$SRC_PATH" "$DEST_PATH"
      fi
    done
  done
else
  echo "No changes detected. Skipping copy step."
fi

echo "Done."
echo "The ELinOS partitions can mount them via NFS."
