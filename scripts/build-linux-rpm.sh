#!/usr/bin/env bash
# Build a local Fedora RPM: PyInstaller engine + Tauri release binary + rpmbuild.
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
app_dir="$repo_dir/app"
engine_dir="$repo_dir/engine"
icons_dir="$app_dir/src-tauri/icons"
rpm_topdir="$app_dir/src-tauri/target/rpmbuild"
staging="$rpm_topdir/SOURCES"

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
  echo "This packaging profile targets Linux x86_64." >&2
  exit 1
fi
for tool in npm cargo rpmbuild; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "$tool is required (rpmbuild: sudo dnf install rpm-build)." >&2
    exit 1
  fi
done
if [[ ! -d "$app_dir/node_modules" ]]; then
  echo "Frontend dependencies are missing. Run 'cd app && npm install' once." >&2
  exit 1
fi

engine_venv="${STEM_STUDIO_ENGINE_VENV:-$engine_dir/.venv311}"
python="$engine_venv/bin/python"
if [[ ! -x "$engine_venv/bin/pyinstaller" ]]; then
  echo "PyInstaller was not found in $engine_venv. Install engine/requirements.txt first." >&2
  exit 1
fi
if ! "$python" -c 'import onnxruntime' >/dev/null 2>&1; then
  echo "onnxruntime is missing from $engine_venv (pip install -r engine/requirements.txt)." >&2
  exit 1
fi

version="$("$python" -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$app_dir/src-tauri/tauri.conf.json")"

echo "==> Packaging the engine with PyInstaller (several GB with CUDA)"
(
  cd "$engine_dir"
  "$engine_venv/bin/pyinstaller" --clean --noconfirm --log-level WARN stem-engine.spec
)

echo "==> Building the Tauri release binary"
(
  cd "$app_dir"
  npm run tauri build -- --no-bundle
)

echo "==> Staging RPM sources"
rm -rf "$rpm_topdir"
mkdir -p "$staging" "$rpm_topdir"/{BUILD,BUILDROOT,RPMS,SPECS,SRPMS}
cp "$app_dir/src-tauri/target/release/stem-studio" "$staging/stem-studio"
cp -a "$engine_dir/dist/stem-engine" "$staging/stem-engine"
cp "$repo_dir/packaging/linux/stem-studio.desktop" "$staging/"
cp "$icons_dir/32x32.png" "$staging/icon-32.png"
cp "$icons_dir/64x64.png" "$staging/icon-64.png"
cp "$icons_dir/128x128.png" "$staging/icon-128.png"
cp "$icons_dir/icon.png" "$staging/icon-512.png"

echo "==> Building the RPM"
rpmbuild -bb \
  --define "_topdir $rpm_topdir" \
  --define "app_version $version" \
  "$repo_dir/packaging/linux/stem-studio.spec"

rpm_path="$(find "$rpm_topdir/RPMS" -name 'stem-studio-*.rpm' | head -n 1)"
echo
echo "RPM: $rpm_path ($(du -h "$rpm_path" | cut -f1))"
echo "Install with: sudo dnf install \"$rpm_path\""
