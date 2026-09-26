#!/usr/bin/env bash
# Sign, notarize and staple a macOS .app with a Developer ID certificate.
#
# Does nothing unless the repository has these Actions secrets:
#   APPLE_CERT_P12       base64 of the exported "Developer ID Application" .p12
#   APPLE_CERT_PASSWORD  password of that .p12
#   APPLE_ID             Apple ID email used for notarization
#   APPLE_TEAM_ID        10-character team ID
#   APPLE_APP_PASSWORD   app-specific password for that Apple ID
set -euo pipefail

app="$1"
if [ -z "${APPLE_CERT_P12:-}" ]; then
  echo "No Developer ID certificate configured; leaving $app unsigned."
  exit 0
fi

keychain="$RUNNER_TEMP/signing.keychain-db"
keychain_password="$(uuidgen)"
echo "$APPLE_CERT_P12" | base64 --decode > "$RUNNER_TEMP/developer-id.p12"
security create-keychain -p "$keychain_password" "$keychain"
security set-keychain-settings -lut 21600 "$keychain"
security unlock-keychain -p "$keychain_password" "$keychain"
security import "$RUNNER_TEMP/developer-id.p12" -P "$APPLE_CERT_PASSWORD" -A -t cert -f pkcs12 -k "$keychain"
security set-key-partition-list -S apple-tool:,apple: -k "$keychain_password" "$keychain" > /dev/null
security list-keychains -d user -s "$keychain" $(security list-keychains -d user | tr -d '"')
rm -f "$RUNNER_TEMP/developer-id.p12"

identity="$(security find-identity -v -p codesigning "$keychain" | awk -F'"' '/Developer ID Application/ { print $2; exit }')"
if [ -z "$identity" ]; then
  echo "The certificate does not contain a Developer ID Application identity." >&2
  exit 1
fi

codesign --force --deep --options runtime --timestamp --sign "$identity" "$app"
codesign --verify --deep --strict --verbose=2 "$app"

ditto -c -k --keepParent "$app" "$RUNNER_TEMP/notarize.zip"
xcrun notarytool submit "$RUNNER_TEMP/notarize.zip" \
  --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD" --wait
xcrun stapler staple "$app"
spctl --assess --type execute --verbose "$app"
