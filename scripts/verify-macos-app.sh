#!/usr/bin/env bash
set -euo pipefail

app_path="${1:-app/src-tauri/target/release/bundle/macos/Stem Studio.app}"
if [[ ! -d "$app_path" ]]; then
  echo "App bundle not found: $app_path" >&2
  exit 1
fi
if [[ ! -x "$app_path/Contents/MacOS/stem-studio" ]]; then
  echo "The main executable is missing from the app bundle." >&2
  exit 1
fi
engine_path="$app_path/Contents/Resources/binaries/stem-engine/stem-engine"
if [[ ! -x "$engine_path" ]]; then
  echo "The packaged onedir engine is missing or not executable." >&2
  exit 1
fi
if [[ ! -x "$app_path/Contents/MacOS/ffmpeg" && ! -x "$app_path/Contents/Resources/ffmpeg" ]]; then
  echo "The packaged FFmpeg executable is missing." >&2
  exit 1
fi

/usr/bin/codesign --verify --deep --strict --verbose=2 "$app_path"
if [[ "${STEM_STUDIO_REQUIRE_NOTARIZATION:-0}" == "1" ]]; then
  /usr/sbin/spctl --assess --type execute --verbose=2 "$app_path"
  /usr/bin/xcrun stapler validate "$app_path"
fi
echo "Validated app bundle: $app_path"
