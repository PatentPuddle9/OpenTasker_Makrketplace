#!/usr/bin/env python3
"""Generate the public catalogue from validated packages and trusted moderation records."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone
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


def trusted_reviewers():
    config = json.loads(Path(".github/marketplace-reviewers.json").read_text(encoding="utf-8"))
    return {str(name).lower() for name in config.get("reviewers", [])}


def last_commit_for(folder):
    return subprocess.check_output(
        ["git", "log", "-1", "--format=%H", "--", folder],
        text=True,
    ).strip()


def approvals_for_package(folder, reviewers):
    commit = last_commit_for(folder)
    if not commit:
        return []
    try:
        prs = api(f"/repos/{os.environ['GITHUB_REPOSITORY']}/commits/{commit}/pulls")
    except Exception as exc:
        print(f"Could not find merged PR for {folder}: {exc}")
        return []

    approved_records = []
    for pr in prs:
        number = pr.get("number")
        if not number:
            continue
        files = api(f"/repos/{os.environ['GITHUB_REPOSITORY']}/pulls/{number}/files?per_page=100")
        if not any(item.get("filename", "").startswith(folder + "/") for item in files):
            continue

        author = ((pr.get("user") or {}).get("login") or "").lower()
        reviews = api(f"/repos/{os.environ['GITHUB_REPOSITORY']}/pulls/{number}/reviews?per_page=100")
        latest_reviews = {}
        for review in reviews:
            login = ((review.get("user") or {}).get("login") or "").lower()
            submitted = review.get("submitted_at") or ""
            if login and submitted >= latest_reviews.get(login, {}).get("submitted_at", ""):
                latest_reviews[login] = review
        approved_records.extend(
            review for login, review in latest_reviews.items()
            if login in reviewers and login != author and review.get("state") == "APPROVED"
        )
        if approved_records:
            continue

        comments = api(f"/repos/{os.environ['GITHUB_REPOSITORY']}/issues/{number}/comments?per_page=100")
        latest_commands = {}
        for comment in comments:
            login = ((comment.get("user") or {}).get("login") or "").lower()
            command = (comment.get("body") or "").strip().lower()
            created = comment.get("created_at") or ""
            if login in reviewers and command in {"/approve-high-risk", "/revoke-high-risk"}:
                if created >= latest_commands.get(login, {}).get("created_at", ""):
                    latest_commands[login] = {
                        "user": {"login": login},
                        "submitted_at": created,
                        "approved": command == "/approve-high-risk",
                    }
        approved_records.extend(item for item in latest_commands.values() if item["approved"])

    return approved_records


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    reviewers = trusted_reviewers()
    suspended = json.loads(Path("moderation/suspended-publishers.json").read_text(encoding="utf-8"))
    suspended_publishers = {str(name).lower() for name in suspended.get("suspendedPublishers", [])}
    decisions = json.loads(Path("moderation/decisions.json").read_text(encoding="utf-8"))
    withdrawn = {
        (item.get("id"), item.get("version"))
        for item in decisions.get("withdrawnPackages", [])
    }

    entries = []
    for manifest_path in sorted(Path("packages").glob("*/*/manifest.json")):
        folder = manifest_path.parent
        result = validate_package(folder)
        if result["errors"]:
            raise SystemExit(f"Refusing to publish invalid package {folder}: " + "; ".join(result["errors"]))

        manifest = result["manifest"]
        package_id, version = manifest["id"], manifest["version"]
        if manifest["publisher"].lower() in suspended_publishers or (package_id, version) in withdrawn:
            print(f"Skipping suspended or withdrawn package {package_id}@{version}.")
            continue

        if result["riskLevel"] == "high":
            approvals = approvals_for_package(folder.as_posix(), reviewers)
            if not approvals:
                print(f"Skipping high-risk package without confirmed moderator approval: {package_id}@{version}")
                continue
            reviewer_names = sorted({
                ((item.get("user") or {}).get("login") or "").strip()
                for item in approvals
                if ((item.get("user") or {}).get("login") or "").strip()
            })
            reviewed_at = max(item.get("submitted_at", "") for item in approvals)
            review_status = "approved"
        else:
            reviewer_names, reviewed_at, review_status = [], None, "automated"

        entries.append({
            "id": package_id,
            "name": manifest["name"],
            "summary": manifest["summary"],
            "category": manifest["category"],
            "publisher": manifest["publisher"],
            "version": version,
            "minimumAppVersion": manifest["minimumAppVersion"],
            "riskLevel": result["riskLevel"],
            "reviewStatus": review_status,
            "reviewedAt": reviewed_at,
            "reviewedBy": reviewer_names,
            "actionIds": result["actionIds"],
            "requiredInputs": manifest.get("requiredInputs", []),
            "externalDestinations": manifest.get("externalDestinations", []),
            "bundlePath": f"{folder.as_posix()}/bundle.json",
            "bundleSha256": result["bundleSha256"],
        })

    entries.sort(key=lambda item: (item["category"].lower(), item["name"].lower(), item["id"], item["version"]))
    catalog = {
        "schemaVersion": 1,
        "marketplaceId": "opentasker-official",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "packages": entries,
    }
    Path("catalog/v1/index.json").write_text(
        json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"Generated {len(entries)} package listing(s) for {repository}.")


if __name__ == "__main__":
    main()
