# Moderation handbook

## Review levels

Risk is computed from action IDs in every task in a bundle. Package metadata cannot lower the computed level.

- Low: ordinary local actions and presentation-only changes. Automated structural and privacy checks apply to first publication.
- Medium: data access or local device configuration that needs additional disclosure.
- High: SMS, contacts, device lock/security controls, settings changes, scripts/plugins, HTTP/API requests, webhooks, MQTT, file transfer, or an unclassified action.

High-risk packages remain visibly high risk after approval. The catalogue stores review status, reviewer login, and review timestamp separately from risk level.

## Trusted reviewers

Edit .github/marketplace-reviewers.json in a moderator-authored pull request to add or remove trusted reviewers. The validator reads the allowlist from the pull request's base commit, so a contributor cannot grant themselves reviewer status in the same pull request.

Every update to an already-published package requires a formal GitHub APPROVED review from a trusted moderator other than the package publisher, regardless of the new version's computed risk level. The comment-based /approve-high-risk command does not satisfy this update requirement. The review workflow re-runs validation when a review is submitted or dismissed.

For a high-risk first publication, a trusted reviewer can submit an APPROVE review or comment /approve-high-risk. A later /revoke-high-risk comment cancels a prior comment approval. A package is not published as reviewed unless the publisher workflow can confirm a trusted approval.

## Reports, deletion, and enforcement

Package reports create GitHub Issues, add the package-report label, assign the issue to PatentPuddle9, and mention the owner. Keep the review record in the issue.

A publisher can delete one of their own packages from the OpenTasker app's My Packages screen. The app opens a structured deletion request issue. The deletion workflow verifies that the issue author matches the publisher recorded in every version manifest, then adds a permanent package-ID tombstone to moderation/decisions.json. No human review is required. The signed catalogue stops listing all versions of that package ID after it is rebuilt.

Deletion does not delete historical package files and does not uninstall or modify copies already imported by users. Existing installs remain in place; new Marketplace installs are no longer offered. A deleted package ID cannot be reused. This is intentionally different from a security takedown: moderators can separately withdraw a specific version or suspend a publisher.

A moderator can dismiss a report, request a correction, mark a package version as withdrawn in moderation/decisions.json, suspend a publisher in moderation/suspended-publishers.json, or restore a package or publisher after investigation. Only moderators may edit moderation decisions directly.

## Branch settings to configure

In GitHub repository Settings > Rules > Rulesets, protect main:
- Require the Marketplace validation check to pass.
- Require pull requests for changes to packages, schemas, tools, and moderation files.
- Restrict direct pushes to maintainers.
- Do not allow bypass for ordinary contributors.

Keep trusted reviewers and moderation files editable only by maintainers. Do not grant contributors Actions secrets or write access merely so they can submit packages.
