#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
engine_dir="$repo_dir/engine"
binary_dir="$repo_dir/app/src-tauri/binaries"
ffmpeg_binary="$binary_dir/ffmpeg-aarch64-apple-darwin"

if [[ -n "${STEM_STUDIO_ENGINE_VENV:-}" ]]; then
  engine_venv="$STEM_STUDIO_ENGINE_VENV"
elif [[ -x "$engine_dir/.venv311/bin/pyinstaller" ]]; then
  engine_venv="$engine_dir/.venv311"
else
  engine_venv="$engine_dir/.venv"
fi
pyinstaller="$engine_venv/bin/pyinstaller"

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "This packaging profile targets Apple Silicon (arm64)." >&2
  exit 1
fi

if [[ ! -x "$pyinstaller" ]]; then
  echo "PyInstaller was not found in $engine_venv. Install engine/requirements.txt first." >&2
  exit 1
fi

mkdir -p "$binary_dir"

ffmpeg_source="${STEM_STUDIO_FFMPEG:-}"
if [[ -z "$ffmpeg_source" ]]; then
  for candidate in /opt/ffmpeg/ffmpeg /opt/homebrew/bin/ffmpeg /usr/local/bin/ffmpeg; do
    if [[ -x "$candidate" ]]; then
      ffmpeg_source="$candidate"
      break
    fi
  done
fi
if [[ -z "$ffmpeg_source" ]] || [[ ! -x "$ffmpeg_source" ]]; then
  echo "FFmpeg was not found. Set STEM_STUDIO_FFMPEG to its executable path." >&2
  exit 1
fi
if ! /usr/bin/lipo "$ffmpeg_source" -verify_arch arm64; then
  echo "The selected FFmpeg binary does not contain the arm64 architecture." >&2
  exit 1
fi
ffmpeg_buildconf="$($ffmpeg_source -hide_banner -buildconf 2>&1)"
for forbidden_option in --enable-gpl --enable-nonfree --enable-libx264 --enable-libx265; do
  if [[ "$ffmpeg_buildconf" == *"$forbidden_option"* ]]; then
    echo "The selected FFmpeg enables $forbidden_option and is not accepted for this LGPL bundle." >&2
    echo "Provide an arm64 FFmpeg built without GPL/nonfree codecs through STEM_STUDIO_FFMPEG." >&2
    exit 1
  fi
done

(
  cd "$engine_dir"
  "$pyinstaller" --clean --noconfirm stem-engine.spec
)

rm -rf "$binary_dir/stem-engine"
cp -R "$engine_dir/dist/stem-engine" "$binary_dir/stem-engine"
chmod +x "$binary_dir/stem-engine/stem-engine"
cp "$ffmpeg_source" "$ffmpeg_binary"
chmod +x "$ffmpeg_binary"

echo "Packaged onedir engine: $binary_dir/stem-engine"
echo "Packaged FFmpeg: $ffmpeg_binary"
echo "Large model weights are not bundled; the app downloads them on first use."
