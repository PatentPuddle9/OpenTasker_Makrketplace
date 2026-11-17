#!/usr/bin/env python3
"""Validate package PRs using scripts from the trusted base branch, never PR-supplied code."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from validate_marketplace import validate_package

STABLE_VERSION = re.compile(r"^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")


def api(path):
    request = urllib.request.Request(
        "https://api.github.com" + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def git_show(commit, path):
    return subprocess.check_output(["git", "show", f"{commit}:{path}"])


def changed_paths(base, head):
    output = subprocess.check_output(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        text=True,
    )
    return [line for line in output.splitlines() if line]


def parse_version(value):
    match = STABLE_VERSION.fullmatch(str(value))
    if not match:
        raise ValueError(f"version '{value}' must use stable numeric MAJOR.MINOR.PATCH format.")
    return tuple(int(part) for part in match.groups())


def allowed_next_versions(current):
    major, minor, patch = parse_version(current)
    return [
        f"{major}.{minor}.{patch + 1}",
        f"{major}.{minor + 1}.0",
        f"{major + 1}.0.0",
    ]


def package_history(base, package_id):
    listing = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", base, "--", f"packages/{package_id}"],
        text=True,
    )
    manifests = []
    for path in listing.splitlines():
        if not path.endswith("/manifest.json"):
            continue
        manifest = json.loads(git_show(base, path))
        manifests.append((path.rsplit("/", 2)[1], manifest))
    return manifests


def latest_by_user(items, timestamp_field):
    latest = {}
    for item in items:
        login = ((item.get("user") or {}).get("login") or "").lower()
        timestamp = item.get(timestamp_field) or ""
        if login and timestamp >= latest.get(login, {}).get(timestamp_field, ""):
            latest[login] = item
    return latest


def comment_approvals(comments, moderators):
    latest = {}
    for comment in comments:
        login = ((comment.get("user") or {}).get("login") or "").lower()
        command = (comment.get("body") or "").strip().lower()
        if login in moderators and command in {"/approve-high-risk", "/revoke-high-risk"}:
            created = comment.get("created_at") or ""
            if created >= latest.get(login, {}).get("created_at", ""):
                latest[login] = {
                    "created_at": created,
                    "approved": command == "/approve-high-risk",
                    "login": login,
                }
    return [item for item in latest.values() if item["approved"]]


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    pr_number = int(os.environ["PR_NUMBER"])
    base = os.environ["BASE_SHA"]
    head = os.environ["HEAD_SHA"]
    pr = api(f"/repos/{repository}/pulls/{pr_number}")
    author = pr["user"]["login"].lower()
    paths = changed_paths(base, head)

    try:
        reviewer_config = json.loads(git_show(base, ".github/marketplace-reviewers.json"))
        moderators = {str(name).lower() for name in reviewer_config.get("reviewers", [])}
        suspended_config = json.loads(git_show(base, "moderation/suspended-publishers.json"))
        suspended = {str(name).lower() for name in suspended_config.get("suspendedPublishers", [])}
        decisions = json.loads(git_show(base, "moderation/decisions.json"))
        deleted_ids = {
            str(item.get("id", "")).lower()
            for item in decisions.get("deletedPackages", [])
            if isinstance(item, dict)
        }
    except Exception as exc:
        raise SystemExit(f"Could not load trusted moderation configuration from base branch: {exc}")

    if author in suspended:
        raise SystemExit(f"Publisher @{author} is suspended from submitting marketplace packages.")

    protected = [
        path for path in paths
        if path.startswith(("moderation/", ".github/marketplace-reviewers.json", ".github/CODEOWNERS", ".github/PULL_REQUEST_TEMPLATE.md", ".github/workflows/", ".github/ISSUE_TEMPLATE/", "tools/", "schemas/", "docs/")) or path in {"README.md", "CONTRIBUTING.md", "SECURITY.md"}
    ]
    if protected and author not in moderators:
        raise SystemExit("Only an existing moderator may change reviewer, moderation, validator, or schema files.")

    package_folders = sorted({
        "/".join(path.split("/")[:3])
        for path in paths
        if path.startswith("packages/") and len(path.split("/")) >= 4
    })
    if len(package_folders) > 1:
        raise SystemExit("Submit one package version per pull request so review and version history stay unambiguous.")

    highest_risk = "low"
    errors = []
    is_update = False

    for folder in package_folders:
        try:
            try:
                git_show(base, f"{folder}/manifest.json")
                errors.append(f"{folder}: published package versions are immutable; submit a new version directory.")
                continue
            except subprocess.CalledProcessError:
                pass

            package_id = folder.split("/")[1]
            folder_version = folder.split("/")[2]
            if package_id.lower() in deleted_ids:
                errors.append(f"{folder}: this package ID has been permanently withdrawn and cannot be republished. Choose a new package ID.")
                continue

            prior_versions = package_history(base, package_id)
            if prior_versions:
                is_update = True
                prior_publishers = {
                    str(manifest.get("publisher", "")).lower()
                    for _, manifest in prior_versions
                }
                if prior_publishers != {author}:
                    errors.append(f"{folder}: only the original publisher may submit updates to this package.")
                    continue
                try:
                    latest_version = max(
                        (parse_version(manifest.get("version", "")), str(manifest.get("version", "")))
                        for _, manifest in prior_versions
                    )[1]
                    allowed = allowed_next_versions(latest_version)
                    parse_version(folder_version)
                    if folder_version not in allowed:
                        errors.append(
                            f"{folder}: version must be exactly one step above latest published version "
                            f"{latest_version}. Allowed next versions: {', '.join(allowed)}."
                        )
                        continue
                except ValueError as exc:
                    errors.append(f"{folder}: {exc}")
                    continue
            else:
                if folder_version != "1.0.0":
                    errors.append(f"{folder}: a new package must start at version 1.0.0.")
                    continue

            with tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / "packages" / package_id / folder_version
                target.mkdir(parents=True, exist_ok=True)
                for filename in ("manifest.json", "bundle.json"):
                    raw = git_show(head, f"{folder}/{filename}")
                    (target / filename).write_bytes(raw)
                result = validate_package(target)

            manifest = result["manifest"]
            if str(manifest.get("publisher", "")).lower() != author:
                errors.append(f"{folder}: manifest publisher must match the pull request author (@{author}).")
            errors.extend(f"{folder}: {message}" for message in result["errors"])
            if result["riskLevel"] == "high":
                highest_risk = "high"
            elif result["riskLevel"] == "medium" and highest_risk == "low":
                highest_risk = "medium"
            for warning in result["warnings"]:
                print(f"WARNING {folder}: {warning}")
        except Exception as exc:
            errors.append(f"{folder}: {exc}")

    if errors:
        raise SystemExit("\\n".join(errors))
    if not package_folders:
        print("No package files changed; repository policy checks passed.")
        return

    print(f"Validated {len(package_folders)} package folder(s); computed highest risk: {highest_risk}.")

    # Every edit to an already-published package requires a formal approval from a trusted,
    # non-author moderator, regardless of the updated bundle's computed risk level. The legacy
    # comment command remains available only for the existing high-risk first-publication path.
    reviews = api(f"/repos/{repository}/pulls/{pr_number}/reviews?per_page=100")
    latest_reviews = latest_by_user(reviews, "submitted_at")
    approved = [
        login for login, review in latest_reviews.items()
        if login in moderators and login != author and review.get("state") == "APPROVED"
    ]
    if is_update:
        if approved:
            print("Package update formally approved by trusted reviewer(s): " + ", ".join(sorted(approved)))
            return
        raise SystemExit(
            "Updates to published packages require a formal APPROVED review from a trusted Marketplace moderator "
            "other than the package publisher. Comment approvals do not replace this review."
        )

    if highest_risk != "high":
        print("No manual moderator approval is required for this low/medium-risk first publication.")
        return

    if approved:
        print("High-risk package approved by trusted reviewer(s): " + ", ".join(sorted(approved)))
        return

    comments = api(f"/repos/{repository}/issues/{pr_number}/comments?per_page=100")
    approvals = comment_approvals(comments, moderators)
    if approvals:
        print("High-risk package approved by trusted moderator command(s): " + ", ".join(sorted(x["login"] for x in approvals)))
        return

    raise SystemExit(
        "High-risk package requires trusted moderator approval. Submit an APPROVE review, "
        "or have a moderator comment /approve-high-risk. A later /revoke-high-risk comment cancels a comment approval."
    )


if __name__ == "__main__":
    main()
