#!/usr/bin/env python3
"""Validate package PRs using scripts from the trusted base branch, never PR-supplied code."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from validate_marketplace import validate_package


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
    except Exception as exc:
        raise SystemExit(f"Could not load trusted moderation configuration from base branch: {exc}")

    if author in suspended:
        raise SystemExit(f"Publisher @{author} is suspended from submitting marketplace packages.")

    protected = [
        path for path in paths
        if path.startswith(("moderation/", ".github/marketplace-reviewers.json", "tools/", "schemas/"))
    ]
    if protected and author not in moderators:
        raise SystemExit("Only an existing moderator may change reviewer, moderation, validator, or schema files.")

    package_folders = sorted({
        "/".join(path.split("/")[:3])
        for path in paths
        if path.startswith("packages/") and len(path.split("/")) >= 4
    })
    highest_risk = "low"
    errors = []

    for folder in package_folders:
        try:
            with tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / "packages" / folder.split("/")[1] / folder.split("/")[2]
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
    if highest_risk != "high":
        print("No manual moderator approval is required for this low/medium-risk contribution.")
        return

    reviews = api(f"/repos/{repository}/pulls/{pr_number}/reviews?per_page=100")
    latest_reviews = latest_by_user(reviews, "submitted_at")
    approved = [
        login for login, review in latest_reviews.items()
        if login in moderators and login != author and review.get("state") == "APPROVED"
    ]
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
