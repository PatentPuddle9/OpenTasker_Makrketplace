# OpenTasker Community Marketplace

A GitHub-native catalogue for reusable OpenTasker actions, automations, and Widget Display scenes.

There is no application server. GitHub stores packages and the signed catalogue, pull requests are the submission mechanism, and GitHub Actions performs automated validation and catalogue publishing.

## How it works

1. A creator exports a sanitized OpenTasker bundle and prepares a package manifest.
2. They submit the package in a pull request under packages/<package-id>/<version>/.
3. GitHub Actions validates the bundle, checks required inputs and external destinations, scans for personal data and credentials, and calculates the package risk level.
4. Low- and medium-risk packages can pass automated moderation. High-risk packages require approval from an account in .github/marketplace-reviewers.json.
5. A maintainer merges the pull request. The publishing workflow rebuilds and signs the catalogue.
6. OpenTasker verifies the catalogue signature and package hash, then sends the bundle through its normal import, capability, and risk review.

Marketplace approval is not a guarantee that an automation is harmless. The app continues to show the risk level after approval.

When a package is deleted, its repository files are removed and its package ID becomes available for a new listing. Reused IDs start a fresh version history at `1.0.0`; previously imported automations remain on users' devices. Deletion records are retained for audit history only.

## Repository layout

- packages/ — versioned package manifests and OpenTasker bundles.
- catalog/v1/ — generated catalogue and detached signature.
- schemas/ — package manifest schema.
- moderation/ — publisher suspensions and package takedown decisions.
- .github/marketplace-reviewers.json — trusted reviewer allowlist.
- tools/ — validation and catalogue generation.
- docs/ — signing and moderation instructions.

## Security model

- Packages are data-only OpenTasker bundles. Arbitrary scripts, native binaries, APKs, executable files, and plugin code are not accepted.
- Unknown action IDs are treated as high risk and remain subject to the app's fail-closed capability checks.
- SMS, device locking, security/settings changes, contacts, API requests, webhooks, MQTT, and other external transmissions or device-control actions are high risk.
- Sensitive values must be replaced with declared input placeholders before submission.
- Every external destination must be declared with its domain, operator, hosting location, privacy-policy URL, purpose, and data fields.
- The official catalogue is signed with an ECDSA P-256 key. The private key belongs only in the MARKETPLACE_SIGNING_PRIVATE_KEY_B64 GitHub Actions secret. The app contains only the public key.
- Imported packages cannot grant Android permissions or bypass OpenTasker's own capability checks.

See CONTRIBUTING.md, SECURITY.md, and docs/SIGNING_KEYS.md before submitting or reviewing a package.

## Initial setup

The initial catalogue is empty and unsigned until the owner provisions the signing key. Follow docs/SIGNING_KEYS.md, add the private key as a GitHub Actions secret, and pin the matching public key in the OpenTasker app repository. Until that is done, the app must not treat the catalogue as verified or allow marketplace installation.
