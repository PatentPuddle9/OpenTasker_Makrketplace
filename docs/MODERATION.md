# Moderation handbook

## Review levels

Risk is computed from action IDs in every task in a bundle. Package metadata cannot lower the computed level.

- Low: ordinary local actions and presentation-only changes. Automated structural and privacy checks apply.
- Medium: data access or local device configuration that needs additional disclosure.
- High: SMS, contacts, device lock/security controls, settings changes, scripts/plugins, HTTP/API requests, webhooks, MQTT, file transfer, or an unclassified action.

High-risk packages remain visibly high risk after approval. The catalogue stores review status, reviewer login, and review timestamp separately from risk level.

## Trusted reviewers

Edit .github/marketplace-reviewers.json in a moderator-authored pull request to add or remove trusted reviewers. The validator reads the allowlist from the pull request's base commit, so a contributor cannot grant themselves reviewer status in the same pull request.

For a high-risk package, a trusted reviewer can submit an APPROVE review or comment /approve-high-risk. A later /revoke-high-risk comment cancels a prior comment approval. A package is not published as reviewed unless the publisher workflow can confirm a trusted approval.

## Reports and enforcement

Package reports create GitHub Issues, add the package-report label, assign the issue to PatentPuddle9, and mention the owner. Keep the review record in the issue.

A moderator can dismiss a report, request a correction, mark a package version as withdrawn in moderation/decisions.json, suspend a publisher in moderation/suspended-publishers.json, or restore a package or publisher after investigation.

Removing a package from the catalogue does not silently remove it from existing devices. OpenTasker should surface the signed takedown notice and let its local safety policy disable or remove the affected package. Confirmed malicious package notices should identify the affected ID and version.

## Branch settings to configure

In GitHub repository Settings > Rules > Rulesets, protect main:
- Require the Marketplace validation check to pass.
- Require pull requests for changes to packages, schemas, tools, and moderation files.
- Restrict direct pushes to maintainers.
- Do not allow bypass for ordinary contributors.

Keep trusted reviewers and moderation files editable only by maintainers. Do not grant contributors Actions secrets or write access merely so they can submit packages.
