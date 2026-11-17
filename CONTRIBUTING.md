# Contributing a package

Thanks for contributing to the OpenTasker marketplace.

## Package structure

Create a new versioned directory:

packages/<package-id>/<version>/
  manifest.json
  bundle.json

Use a lowercase package ID containing letters, numbers, dots, underscores, or hyphens. A new package starts at version 1.0.0. Do not overwrite an existing published version; submit a new version directory instead.

For an update, increase exactly one semantic-version component by one step. From 1.1.2, the only valid next versions are 1.1.3, 1.2.0, and 2.0.0. Skipped or combined increments are rejected.

The bundle must be a normal OpenTasker JSON bundle produced by OpenTasker. It may contain actions, profiles, variables, and scenes. It must not contain arbitrary code, scripts, APKs, native libraries, executable files, or plugin binaries.

See [docs/PACKAGE_FORMAT.md](docs/PACKAGE_FORMAT.md) for a complete manifest example and input placeholder format.

## Protect personal information

Do not submit a live automation export containing personal data. Before submitting:

- Replace phone numbers, contact identifiers, email addresses, addresses, tokens, passwords, API keys, webhook secrets, and private URLs with inputs.
- Use a bundle string such as {{input:recipient}} where the user must supply a value.
- Declare each input in manifest.json, including its JSON Pointer path, label, type, and whether it is required.
- Keep secrets out of package descriptions, screenshots, filenames, issue reports, and metadata.
- Never include real SMS recipients or private message content.

The validator rejects detected personal data and credentials. It does not silently sanitize submitted repository files; creators must correct the package before it can be merged.

## External services

Every external service must be declared in externalDestinations. Include the provider/operator, exact domain, hosting country (or "Unknown"), privacy policy URL, data fields sent, purpose, and any known privacy concerns.

HTTP/API requests, Home Assistant webhooks, MQTT, SMS, and other external transmissions are high risk. A package with those capabilities requires moderator approval before it can be published. A missing or undeclared destination fails validation.

Do not claim that a service is safe simply because it uses HTTPS or is hosted in a particular country. Unknown hosting, unknown ownership, or an unverified privacy policy must be disclosed.

## Review and publishing

Open a pull request with a clear description of what the automation does and why each sensitive capability is needed.

GitHub Actions runs automated checks. Low- and medium-risk first publications can pass without manual content review. High-risk first publications require approval from a trusted moderator listed in .github/marketplace-reviewers.json.

Every update to an existing package requires a formal APPROVED GitHub review from another repository collaborator with write access, regardless of risk. The publisher cannot approve their own update, and a comment command is not a substitute for this review. High-risk updates also require trusted-moderator approval. The app creates each update as a new immutable version and opens a pull request; the update does not appear in the catalogue until it is approved and merged.

A successful CI check does not publish a package by itself. A maintainer must merge the pull request. The publish workflow then rebuilds and signs the catalogue.

Never add yourself to the moderator list in the same contribution that you are asking to be reviewed. Changes to reviewer, moderation, and policy files are restricted to existing moderators.

## Managing and deleting packages

Publishers can use **Marketplace → My Packages** in OpenTasker to submit an update or request deletion. Updates use the new-version review process above.

Deletion does not require review. The app creates a structured request issue, and GitHub Actions verifies that the issue author is the publisher recorded in the package manifests before adding a permanent tombstone. All versions disappear from the signed catalogue after it is rebuilt. Historical bundle files remain in the repository, and copies already installed by users remain installed and unchanged. Deleted package IDs cannot be reused.

## Reports and takedowns

Use the package report issue form for malicious behavior, privacy concerns, broken automations, undisclosed destinations, or suspicious rapid execution. Include the package ID and version, but never paste private credentials or personal contact information.

A report does not automatically remove a package. A moderator investigates and may dismiss the report, request a correction, suspend a version, remove a package, or suspend a publisher.
