# Official marketplace signing-key setup

The official catalogue uses **ECDSA P-256 / SHA-256** signatures. Keep the private signing key out of the Android app.

## Two linked values, not one shared secret

This setup uses a key pair:

- **Marketplace repository** `PatentPuddle9/OpenTasker_Makrketplace`: add the base64-encoded PEM **private key** as the GitHub Actions secret `MARKETPLACE_SIGNING_PRIVATE_KEY_B64`. It is used only by the catalogue-publishing workflow. Never put it in the app repository, an APK, source code, an issue, or a chat.
- **App repository** `PatentPuddle9/OpenTasker_`: add the matching X.509 SubjectPublicKeyInfo **public key** (Base64-encoded DER) as the GitHub Actions secret `MARKETPLACE_PUBLIC_KEY_X509_BASE64`. The build workflow passes it into Gradle, which embeds only the public key in the app. The public key is not confidential; storing it as an Actions secret simply keeps the source file free of a literal key.

Do **not** put the same private secret in both repositories. An installed app cannot read GitHub Actions secrets. Giving the app the HMAC/private secret would require shipping it inside the APK, where it could be extracted and used to forge marketplace packages.

## Generate the pair

Download [tools/signing-key-generator.html](../tools/signing-key-generator.html) from this repository (use GitHub's Download raw file option), then open the downloaded HTML file in Chrome. It uses the browser's built-in Web Crypto API and makes no network requests. Generate the pair locally; the private value must never be uploaded to a third-party service.

The private-key Actions secret must contain Base64 of the complete PEM text, including its BEGIN/END lines. The app public-key Actions secret must contain Base64 of the public key's X.509 SubjectPublicKeyInfo DER bytes (not PEM text).

## Configure the GitHub Actions secrets

In each repository, open **Settings → Secrets and variables → Actions → New repository secret**.

| Repository | Secret name | Value |
|---|---|---|
| `PatentPuddle9/OpenTasker_Makrketplace` | `MARKETPLACE_SIGNING_PRIVATE_KEY_B64` | Base64-encoded PEM private key |
| `PatentPuddle9/OpenTasker_` | `MARKETPLACE_PUBLIC_KEY_X509_BASE64` | Base64-encoded X.509 SPKI public key |

The app build reads the public-key secret from the environment and writes it into the generated BuildConfig field. If the secret is missing, the build remains possible but marketplace verification stays fail-closed and marketplace downloads remain disabled.

## Publish and verify

After both secrets are configured:

1. Run **Build OpenTasker APK** on the `Experimental` branch.
2. Run **Publish signed marketplace catalogue** in the marketplace repository.
3. Install the new APK and confirm it accepts the official catalogue.
4. Confirm that a modified catalogue and modified package are rejected.

## Rotation

For rotation, first ship an app update containing the new public key, then switch the marketplace private-key secret to the matching private key after the app update is available. Plan a transition window if older app versions still need to read the old catalogue. Never trust a public key downloaded from the same untrusted catalogue it is meant to verify.
