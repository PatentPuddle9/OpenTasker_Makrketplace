#!/usr/bin/env python3
"""Generate the public catalogue from validated packages and trusted moderation records."""
# Keep this module in the publish workflow so catalogue-policy CI exercises it with the deletion processor.

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import urllib.request
from datetime import datetime, timedelta, timezone
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


def published_at_for(folder):
    commit = last_commit_for(folder)
    if not commit:
        return ""
    try:
        return subprocess.check_output(["git", "show", "-s", "--format=%cI", commit], text=True).strip()
    except Exception:
        return ""


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
    quarantined = {
        (item.get("id"), item.get("version"))
        for item in decisions.get("quarantinedPackages", [])
        if isinstance(item, dict)
    }
    ratings_data = json.loads(Path("moderation/ratings.json").read_text(encoding="utf-8"))
    ratings_by_package = {}
    for rating in ratings_data.get("ratings", []):
        package_id = str(rating.get("packageId", "")).strip().lower()
        user_id = rating.get("userId")
        stars = rating.get("stars")
        if package_id and isinstance(user_id, int) and user_id > 0 and type(stars) is int and 1 <= stars <= 5:
            ratings_by_package.setdefault(package_id, {})[str(user_id)] = stars
    featured_data = json.loads(Path("moderation/featured-packages.json").read_text(encoding="utf-8"))
    featured_ids = {
        str(item.get("id", "")).strip().lower()
        for item in featured_data.get("packages", [])
        if isinstance(item, dict) and item.get("id")
    }
    reviews_data = json.loads(Path("moderation/reviews.json").read_text(encoding="utf-8"))
    reviews_by_package = {}
    for review in reviews_data.get("reviews", []):
        package_id = str(review.get("packageId", "")).strip().lower()
        user_id = review.get("userId")
        title = str(review.get("title", "")).strip()
        body = str(review.get("body", "")).strip()
        if (
            package_id
            and isinstance(user_id, int)
            and user_id > 0
            and title
            and body
            and str(review.get("moderationStatus", "visible")).casefold() == "visible"
        ):
            reviews_by_package.setdefault(package_id, []).append(review)
    download_data = json.loads(Path("moderation/download-stats.json").read_text(encoding="utf-8"))
    download_stats = download_data.get("packages", {})
    entries = []
    for manifest_path in sorted(Path("packages").glob("*/*/manifest.json")):
        folder = manifest_path.parent
        # Deletion processing removes the withdrawn package directory. The tombstone is
        # retained for audit history only; a newly submitted package may reuse the same ID.
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        package_id, version = manifest["id"], manifest["version"]

        result = validate_package(folder)
        if result["errors"]:
            raise SystemExit(f"Refusing to publish invalid package {folder}: " + "; ".join(result["errors"]))

        manifest = result["manifest"]
        package_id, version = manifest["id"], manifest["version"]
        if (
            manifest["publisher"].lower() in suspended_publishers
            or (package_id, version) in withdrawn
            or (package_id, version) in quarantined
        ):
            print(f"Skipping suspended, withdrawn, or quarantined package {package_id}@{version}.")
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

        rating_votes = ratings_by_package.get(package_id, {})
        rating_count = len(rating_votes)
        rating_average = round(sum(rating_votes.values()) / rating_count, 2) if rating_count else 0.0
        rating_distribution = {
            str(stars): sum(1 for value in rating_votes.values() if value == stars)
            for stars in range(1, 6)
        }
        stats = download_stats.get(package_id, {})
        verified_installers = set(stats.get("uniqueUserIds", [])) if isinstance(stats, dict) else set()
        package_reviews = sorted(
            reviews_by_package.get(package_id, []),
            key=lambda item: str(item.get("updatedAt", item.get("createdAt", ""))),
            reverse=True,
        )[:50]
        public_reviews = [{
            "reviewId": str(item["userId"]),
            "userId": item["userId"],
            "author": str(item.get("author", "Community member")),
            "title": str(item.get("title", "")),
            "body": str(item.get("body", "")),
            "createdAt": str(item.get("createdAt", "")),
            "updatedAt": str(item.get("updatedAt", "")),
            "helpfulCount": len(set(item.get("helpfulUserIds", []))),
            "helpfulUserIds": sorted(set(int(value) for value in item.get("helpfulUserIds", []) if str(value).isdigit())),
            "verifiedInstaller": item.get("userId") in verified_installers,
            "publisherResponse": item.get("publisherResponse") if isinstance(item.get("publisherResponse"), dict) else None,
        } for item in package_reviews]
        published_at = published_at_for(folder.as_posix())
        daily_downloads = stats.get("daily", []) if isinstance(stats, dict) else []
        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=6)).isoformat()
        weekly_downloads = sum(
            max(0, int(item.get("count", 0)))
            for item in daily_downloads
            if isinstance(item, dict) and str(item.get("date", "")) >= cutoff
        )
        screenshot_entries = [{
            "path": f"{folder.as_posix()}/{name}",
            "sha256": hashlib.sha256((folder / name).read_bytes()).hexdigest(),
        } for name in manifest.get("screenshots", [])]
        entries.append({
            "id": package_id,
            "name": manifest["name"],
            "summary": manifest["summary"],
            "description": manifest.get("description", ""),
            "tags": manifest.get("tags", []),
            "icon": manifest.get("icon", "bolt"),
            "iconColor": manifest.get("iconColor", "#FFFFFF"),
            "backgroundColor": manifest.get("backgroundColor", "#6750A4"),
            "gradient": manifest.get("gradient", True),
            "shape": manifest.get("shape", "squircle"),
            "changelog": manifest.get("changelog", ""),
            "documentationUrl": manifest.get("documentationUrl", ""),
            "featured": package_id in featured_ids,
            "ratingAverage": rating_average,
            "ratingCount": rating_count,
            "ratingVotes": dict(sorted(rating_votes.items())),
            "ratingDistribution": rating_distribution,
            "reviews": public_reviews,
            "reviewCount": len(package_reviews),
            "downloadCount": max(0, int(stats.get("totalDownloads", 0))) if isinstance(stats, dict) else 0,
            "uniqueInstallerCount": len(set(stats.get("uniqueUserIds", []))) if isinstance(stats, dict) else 0,
            "weeklyDownloads": weekly_downloads,
            "publishedAt": published_at,
            "faqs": manifest.get("faqs", []),
            "dependencies": manifest.get("dependencies", []),
            "screenshots": screenshot_entries,
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
            "previewPath": f"{folder.as_posix()}/preview.png" if (folder / "preview.png").is_file() else "",
            "previewSha256": hashlib.sha256((folder / "preview.png").read_bytes()).hexdigest() if (folder / "preview.png").is_file() else "",
            "iconAssetPath": f"{folder.as_posix()}/icon.png" if (folder / "icon.png").is_file() else "",
            "iconAssetSha256": hashlib.sha256((folder / "icon.png").read_bytes()).hexdigest() if (folder / "icon.png").is_file() else "",
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
