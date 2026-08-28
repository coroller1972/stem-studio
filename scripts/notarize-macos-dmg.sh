#!/usr/bin/env bash
set -euo pipefail

dmg_path="${1:?Usage: notarize-macos-dmg.sh /path/to/Stem\ Studio.dmg}"
notary_profile="${APPLE_NOTARY_PROFILE:?Set APPLE_NOTARY_PROFILE to an xcrun notarytool keychain profile.}"
if [[ ! -f "$dmg_path" ]]; then
  echo "DMG not found: $dmg_path" >&2
  exit 1
fi

/usr/bin/xcrun notarytool submit "$dmg_path" --keychain-profile "$notary_profile" --wait
/usr/bin/xcrun stapler staple "$dmg_path"
/usr/bin/xcrun stapler validate "$dmg_path"
/usr/sbin/spctl --assess --type open --context context:primary-signature --verbose=2 "$dmg_path"
echo "Notarized and stapled: $dmg_path"
