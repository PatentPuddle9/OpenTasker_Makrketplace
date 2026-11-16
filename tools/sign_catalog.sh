#!/usr/bin/env bash
set -euo pipefail

: "${MARKETPLACE_SIGNING_PRIVATE_KEY_B64:?Set the MARKETPLACE_SIGNING_PRIVATE_KEY_B64 GitHub Actions secret first}"
tmp_key="$(mktemp)"
tmp_sig="$(mktemp)"
cleanup() {
  rm -f "$tmp_key" "$tmp_sig"
}
trap cleanup EXIT

printf '%s' "$MARKETPLACE_SIGNING_PRIVATE_KEY_B64" | base64 --decode > "$tmp_key"
openssl pkey -in "$tmp_key" -noout >/dev/null
openssl dgst -sha256 -sign "$tmp_key" -out "$tmp_sig" catalog/v1/index.json
base64 --wrap=0 "$tmp_sig" > catalog/v1/index.sig
printf '\\n' >> catalog/v1/index.sig
echo "Signed catalog/v1/index.json with the official ECDSA key."
