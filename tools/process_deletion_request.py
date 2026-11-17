#!/usr/bin/env python3
"""Process publisher-authenticated Marketplace deletion issues without human review."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MARKER = "<!-- opentasker-marketplace-delete:v1 -->"
PACKAGE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")


def api(method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        "https://api.github.com" + path,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def finish_issue(repository, number, message):
    api("POST", f"/repos/{repository}/issues/{number}/comments", {"body": message})
    api("PATCH", f"/repos/{repository}/issues/{number}", {"state": "closed"})


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    event_path = os.environ["GITHUB_EVENT_PATH"]
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    issue = event.get("issue") or {}
    if issue.get("pull_request"):
        print("Ignoring pull-request issue event.")
        return

    body = issue.get("body") or ""
    if MARKER not in body:
        print("Issue is not an OpenTasker Marketplace deletion request.")
        return

    number = int(issue.get("number") or 0)
    author = str((issue.get("user") or {}).get("login") or "").strip()
    if not number or not author:
        raise SystemExit("Deletion issue is missing its number or author.")

    try:
        payload_text = body.split(MARKER, 1)[1].strip()
        request = json.loads(payload_text)
        package_id = str(request.get("packageId", "")).strip().lower()
    except Exception:
        finish_issue(repository, number, "Deletion request rejected: the package request data is malformed.")
        return

    if not PACKAGE_ID.fullmatch(package_id):
        finish_issue(repository, number, "Deletion request rejected: the package ID is invalid.")
        return

    manifests = sorted((Path("packages") / package_id).glob("*/manifest.json"))
    if not manifests:
        finish_issue(repository, number, f"Deletion request rejected: package `{package_id}` does not exist.")
        return

    publishers = set()
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if str(manifest.get("id", "")).lower() != package_id:
            finish_issue(repository, number, "Deletion request rejected: a package manifest does not match its folder.")
            return
        publishers.add(str(manifest.get("publisher", "")).lower())

    if publishers != {author.lower()}:
        finish_issue(
            repository,
            number,
            "Deletion request rejected: only the original publisher recorded in the package manifest can delete it.",
        )
        return

    decisions_path = Path("moderation/decisions.json")
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(
        ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
        check=True,
    )

    published = False
    for attempt in range(1, 4):
        # A catalogue publisher may push to main while this deletion is being processed.
        # Refresh and rebuild the tombstone from the newest main instead of losing either change.
        subprocess.run(["git", "fetch", "origin", "main"], check=True)
        subprocess.run(["git", "reset", "--hard", "origin/main"], check=True)

        decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
        deleted = decisions.setdefault("deletedPackages", [])
        if not isinstance(deleted, list):
            raise SystemExit("moderation/decisions.json deletedPackages must be an array.")
        issue_url = str(issue.get("html_url", ""))
        if any(
            str(item.get("requestUrl", "")) == issue_url
            for item in deleted
            if isinstance(item, dict)
        ):
            finish_issue(
                repository,
                number,
                f"Deletion request for `{package_id}` was already processed. The package ID remains available for a new listing.",
            )
            return

        # Re-check the current main checkout after the concurrency-safe refresh. All versions
        # of the active package generation must still belong to the authenticated publisher.
        package_dir = Path("packages") / package_id
        manifests = sorted(package_dir.glob("*/manifest.json"))
        if not manifests:
            finish_issue(repository, number, f"Deletion request rejected: package `{package_id}` no longer exists.")
            return
        current_publishers = set()
        for manifest_path in manifests:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if str(manifest.get("id", "")).lower() != package_id:
                finish_issue(repository, number, "Deletion request rejected: a package manifest does not match its folder.")
                return
            current_publishers.add(str(manifest.get("publisher", "")).lower())
        if current_publishers != {author.lower()}:
            finish_issue(
                repository,
                number,
                "Deletion request rejected: only the current publisher recorded in the active package manifests can delete it.",
            )
            return

        decisions["deletedPackages"] = deleted + [{
            "id": package_id,
            "publisher": author,
            "deletedAt": datetime.now(timezone.utc).isoformat(),
            "requestUrl": issue_url,
        }]

        # Free the package ID by removing all immutable files from the old generation.
        # Imported copies on users' devices are unaffected. The deletion record above remains
        # as an audit trail, but it no longer reserves the ID.
        shutil.rmtree(package_dir)

        # Version-specific withdrawal decisions from the removed generation must not block a
        # future package that legitimately reuses the same ID and starts again at 1.0.0.
        withdrawn = decisions.setdefault("withdrawnPackages", [])
        if not isinstance(withdrawn, list):
            raise SystemExit("moderation/decisions.json withdrawnPackages must be an array.")
        decisions["withdrawnPackages"] = [
            item for item in withdrawn
            if not (isinstance(item, dict) and str(item.get("id", "")).lower() == package_id)
        ]

        # Ratings and featured status belong to a package generation. A fresh package
        # reusing the same ID must start with no inherited stars or featured placement.
        ratings_path = Path("moderation/ratings.json")
        ratings_data = json.loads(ratings_path.read_text(encoding="utf-8"))
        ratings_data["ratings"] = [
            item for item in ratings_data.get("ratings", [])
            if not (isinstance(item, dict) and str(item.get("packageId", "")).lower() == package_id)
        ]
        ratings_path.write_text(
            json.dumps(ratings_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        featured_path = Path("moderation/featured-packages.json")
        featured_data = json.loads(featured_path.read_text(encoding="utf-8"))
        featured_data["packages"] = [
            item for item in featured_data.get("packages", [])
            if not (isinstance(item, dict) and str(item.get("id", "")).lower() == package_id)
        ]
        featured_path.write_text(
            json.dumps(featured_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        reviews_path = Path("moderation/reviews.json")
        reviews_data = json.loads(reviews_path.read_text(encoding="utf-8"))
        reviews_data["reviews"] = [
            item for item in reviews_data.get("reviews", [])
            if not (isinstance(item, dict) and str(item.get("packageId", "")).lower() == package_id)
        ]
        reviews_path.write_text(
            json.dumps(reviews_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        downloads_path = Path("moderation/download-stats.json")
        downloads_data = json.loads(downloads_path.read_text(encoding="utf-8"))
        downloads_data.setdefault("packages", {}).pop(package_id, None)
        downloads_path.write_text(
            json.dumps(downloads_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        decisions_path.write_text(
            json.dumps(decisions, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "add", "-A", "--", str(package_dir), "moderation/decisions.json",
             "moderation/ratings.json", "moderation/featured-packages.json",
             "moderation/reviews.json", "moderation/download-stats.json"],
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"Withdraw Marketplace package {package_id}"],
            check=True,
        )
        push = subprocess.run(
            ["git", "push", "origin", "HEAD:main"],
            text=True,
            capture_output=True,
        )
        if push.returncode == 0:
            published = True
            break
        print(f"Push attempt {attempt} raced with another main update: {push.stderr.strip()}")

    if not published:
        raise SystemExit("Could not publish the deletion tombstone after three attempts; the request can be retried.")

    try:
        api(
            "POST",
            f"/repos/{repository}/actions/workflows/publish-catalog.yml/dispatches",
            {"ref": "main"},
        )
    except Exception as exc:
        print(f"Could not queue the signed catalogue refresh: {exc}")
        api(
            "POST",
            f"/repos/{repository}/issues/{number}/comments",
            {"body": "The package deletion was saved, but the signed catalogue refresh could not be queued automatically. A maintainer must run the Publish signed marketplace catalogue workflow."},
        )

    finish_issue(
        repository,
        number,
        f"Package `{package_id}` has been withdrawn from the Marketplace. Its old package files were removed and its ID is now free for a new listing. "
        "Automations already imported by users remain installed and unchanged. A reused ID starts a fresh package at version 1.0.0.",
    )
    print(f"Deleted Marketplace listing for {package_id}; removed old package files and freed the ID. Existing installed copies are untouched.")


if __name__ == "__main__":
    main()
