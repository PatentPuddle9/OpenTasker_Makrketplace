# Security policy

## Reporting a vulnerability

Use the GitHub issue form labeled Package report for marketplace package concerns. For vulnerabilities in OpenTasker itself or in the marketplace validation/signing pipeline, do not publish exploit details in a public issue. Contact the repository owner privately through GitHub.

Never include phone numbers, access tokens, passwords, API keys, private URLs, or personal information in a report.

## Marketplace threat model

The marketplace accepts data-only OpenTasker bundles. It does not accept executable code or binaries. The app must still validate all action IDs and permissions locally; a catalogue signature proves origin and integrity, not that a package is safe.

High-risk capabilities require manual moderator approval. External destinations must be declared. The app should disclose the exact destination and the information sent, and should not claim a privacy policy or hosting country is verified unless there is evidence.

## Signing key

The official signing private key is stored only as a GitHub Actions secret named MARKETPLACE_SIGNING_PRIVATE_KEY_B64. Never commit it, paste it into an issue or pull request, include it in an app build, or share it with package contributors. If compromised, stop publishing, rotate the key, and update the app's pinned public key through a reviewed app release.
