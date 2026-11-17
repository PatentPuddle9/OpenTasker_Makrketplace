# Moderation handbook

## Review levels

Risk is computed from action IDs in every task in a bundle. Package metadata cannot lower the computed level.

- Low: ordinary local actions and presentation-only changes. Automated structural and privacy checks apply to first publication.
- Medium: data access or local device configuration that needs additional disclosure.
- High: SMS, contacts, device lock/security controls, settings changes, scripts/plugins, HTTP/API requests, webhooks, MQTT, file transfer, or an unclassified action.

High-risk packages remain visibly high risk after approval. The catalogue stores review status, reviewer login, and review timestamp separately from risk level.

## Trusted reviewers

Edit .github/marketplace-reviewers.json in a moderator-authored pull request to add or remove trusted reviewers. The validator reads the allowlist from the pull request's base commit, so a contributor cannot grant themselves reviewer status in the same pull request.

Every update to an already-published package requires a formal GitHub APPROVED review from another repository collaborator with write access, regardless of the new version's computed risk level. The package publisher cannot approve their own update. High-risk updates also need the additional trusted-moderator approval described below. The comment-based /approve-high-risk command does not satisfy the independent update-review requirement. The review workflow re-runs validation when a review is submitted or dismissed.

For a high-risk first publication, a trusted reviewer can submit an APPROVE review or comment /approve-high-risk. A later /revoke-high-risk comment cancels a prior comment approval. A package is not published as reviewed unless the publisher workflow can confirm a trusted approval.

## Ratings and featured packages

Signed-in Marketplace users can submit one 1–5 star rating per package. A later rating from the same GitHub account replaces that account's previous rating; publishers cannot rate their own packages. The processor stores the GitHub numeric account ID and rating, then the signed catalogue publishes the aggregate and current-user rating lookup. Ratings are moderation metadata, not package code.

Only users listed in .github/marketplace-reviewers.json may feature or unfeature a package. Maintainers use the OpenTasker Marketplace package details screen; the app submits a structured request and the workflow validates the issue author against the trusted reviewer list before changing moderation/featured-packages.json. Featured state is published in the signed catalogue and appears in the app's Featured filter.

Deleting a package also clears its ratings, written reviews, helpful votes, featured state, and download statistics. A new package that reuses the ID starts with no inherited community data.

## Reports, deletion, and enforcement

Package reports create GitHub Issues, add the package-report label, assign the issue to PatentPuddle9, and mention the owner. Keep the review record in the issue.

A publisher can delete one of their own packages from the OpenTasker app's My Packages screen. The app opens a structured deletion request issue. The deletion workflow verifies that the issue author matches the publisher recorded in every version manifest, then removes all package-version files and frees the package ID. The signed catalogue stops listing the package after it is rebuilt.

Deletion does not uninstall or modify copies already imported by users. A reused package ID starts a fresh generation at 1.0.0 with no inherited ratings, reviews, helpful votes, featured status, or download statistics. This is intentionally different from a security takedown: moderators can separately withdraw a specific version or suspend a publisher.

A moderator can dismiss a report, request a correction, mark a package version as withdrawn in moderation/decisions.json, suspend a publisher in moderation/suspended-publishers.json, or restore a package or publisher after investigation. Only moderators may edit moderation decisions directly.

## Branch settings to configure

In GitHub repository Settings > Rules > Rulesets, protect main:
- Require the Marketplace validation check to pass.
- Require pull requests for changes to packages, schemas, tools, and moderation files.
- Restrict direct pushes to maintainers.
- Do not allow bypass for ordinary contributors.

Keep trusted reviewers and moderation files editable only by maintainers. Do not grant contributors Actions secrets or write access merely so they can submit packages.


## Written reviews, helpful votes, and install analytics

Signed-in users can publish one review per package and edit it later. The processor validates the package, prevents publishers from reviewing their own listings, limits the review title to 100 characters and body to 1,200 characters, and rejects likely contact details or credentials. Each account can mark another user's review helpful once; self-votes are rejected.

Install events are submitted only by users signed in through the Android app. The processor verifies that the reported package version exists and counts at most one event per GitHub account/package/day. Catalogue fields include total events, unique account count, and a rolling seven-day count. These metrics are install events, not a claim of unique devices or people. Guest users are not tracked.

Reviews and download data are stored under moderation metadata, not inside package bundles. The signed catalogue contains the displayable review and aggregate information consumed by the app. When a package is deleted and its ID is released, these records are cleared for that package ID.


## Review moderation commands

Trusted reviewers may use the following exact commands as comments on any issue in this repository. The workflow verifies the comment author's login against the trusted reviewer allowlist and updates moderation metadata through a bot commit. Ordinary users cannot invoke these commands.

- `/hide-review <package-id> <review-user-id>` hides a public review from the next signed catalogue.
- `/restore-review <package-id> <review-user-id>` restores a previously hidden review.
- `/quarantine <package-id> <version> [reason]` removes one package version from new catalogue installs while preserving its source and audit trail.
- `/restore-package <package-id> <version>` removes the quarantine decision and returns a valid package version to the catalogue.
- `/suspend-publisher <github-login>` withholds all of a publisher's packages from the catalogue.
- `/unsuspend-publisher <github-login>` removes the publisher suspension.

Three independent review reports temporarily mark a review as under review, which withholds it from the public catalogue until a moderator restores or hides it. Reports do not automatically remove a package or suspend its publisher. Quarantining affects new Marketplace installs only; existing user imports remain unchanged.

## Package file restrictions

Package pull requests may contain only `manifest.json`, `bundle.json`, the generated `preview.png`, an optional `icon.png`, and up to four `screenshots/NN.png` files. Each file is limited to 8 MB, the complete version is limited to 20 MB, and extra payload types are rejected. Package PR validation uses trusted validators from the base branch and never executes submitted package code.
