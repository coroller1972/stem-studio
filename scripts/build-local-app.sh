#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
app_dir="$repo_dir/app"
macos_bundle_dir="$app_dir/src-tauri/target/release/bundle/macos"
dmg_bundle_dir="$app_dir/src-tauri/target/release/bundle/dmg"

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "This local build targets Apple Silicon (arm64)." >&2
  exit 1
fi

if [[ ! -d "$app_dir/node_modules" ]]; then
  echo "Frontend dependencies are missing. Run 'cd app && npm install' once." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js/npm is required to build the local application." >&2
  exit 1
fi

if ! command -v cargo >/dev/null 2>&1; then
  echo "Rust/Cargo is required to build the local application." >&2
  exit 1
fi

"$repo_dir/scripts/package-engine.sh"

(
  cd "$app_dir"
  npm run tauri build -- --config src-tauri/tauri.bundle.conf.json
)

"$repo_dir/scripts/verify-macos-app.sh" "$macos_bundle_dir/Stem Studio.app"

echo
echo "Local application build completed."
echo "App bundle: $macos_bundle_dir/Stem Studio.app"
echo "DMG folder: $dmg_bundle_dir"
echo "Open the DMG or drag Stem Studio.app into /Applications."
