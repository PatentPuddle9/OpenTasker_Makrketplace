#!/usr/bin/env python3
"""Process signed-in Marketplace rating and maintainer featuring requests."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RATING_MARKER = "<!-- opentasker-marketplace-rate:v1 -->"
FEATURE_MARKER = "<!-- opentasker-marketplace-feature:v1 -->"
REVIEW_MARKER = "<!-- opentasker-marketplace-review:v1 -->"
HELPFUL_MARKER = "<!-- opentasker-marketplace-helpful:v1 -->"
DOWNLOAD_MARKER = "<!-- opentasker-marketplace-download:v1 -->"
PUBLISHER_RESPONSE_MARKER = "<!-- opentasker-marketplace-publisher-response:v1 -->"
REVIEW_REPORT_MARKER = "<!-- opentasker-marketplace-review-report:v1 -->"
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE = re.compile(r"(?<!\w)(?:\+?1[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]?\d{4}(?!\w)")
SECRET = re.compile(r"(?i)\b(?:bearer\s+\S{12,}|(?:gh[pousr]?|sk)_[A-Za-z0-9_-]{16,}|(?:token|password|api.?key)\s*[:=]\s*\S{8,})")
PACKAGE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")


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


def parse_request(body, marker):
    if marker not in body:
        return None
    return json.loads(body.split(marker, 1)[1].strip())


def package_manifests(package_id):
    folder = Path("packages") / package_id
    manifests = sorted(folder.glob("*/manifest.json"))
    valid = []
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if str(manifest.get("id", "")).lower() != package_id:
            raise ValueError("A package manifest does not match its package directory.")
        if not SEMVER.fullmatch(str(manifest.get("version", ""))) or path.parent.name != manifest["version"]:
            raise ValueError("A package version directory is invalid.")
        valid.append((path, manifest))
    return valid


def trusted_reviewers():
    config = json.loads(Path(".github/marketplace-reviewers.json").read_text(encoding="utf-8"))
    return {str(name).strip().casefold() for name in config.get("reviewers", [])}


def dispatch_catalog_publish(repository):
    api(
        "POST",
        f"/repos/{repository}/actions/workflows/publish-catalog.yml/dispatches",
        {"ref": "main"},
    )


def configure_bot():
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(
        ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
        check=True,
    )


def save_with_retry(path, content, message):
    configure_bot()
    for attempt in range(1, 4):
        subprocess.run(["git", "fetch", "origin", "main"], check=True)
        subprocess.run(["git", "reset", "--hard", "origin/main"], check=True)
        path.write_text(content(), encoding="utf-8")
        subprocess.run(["git", "add", "--", str(path)], check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
            return True
        subprocess.run(["git", "commit", "-m", message], check=True)
        push = subprocess.run(
            ["git", "push", "origin", "HEAD:main"],
            text=True,
            capture_output=True,
        )
        if push.returncode == 0:
            return True
        print(f"Push attempt {attempt} raced with another main update: {push.stderr.strip()}")
    return False



def persist_json_update(path, update, commit_message):
    repository = os.environ["GITHUB_REPOSITORY"]
    for attempt in range(1, 4):
        subprocess.run(["git", "fetch", "origin", "main"], check=True)
        subprocess.run(["git", "reset", "--hard", "origin/main"], check=True)
        data = json.loads(path.read_text(encoding="utf-8"))
        changed, reply = update(data)
        if not changed:
            return reply
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        configure_bot()
        subprocess.run(["git", "add", "--", str(path)], check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
            return reply
        subprocess.run(["git", "commit", "-m", commit_message], check=True)
        push = subprocess.run(["git", "push", "origin", "HEAD:main"], text=True, capture_output=True)
        if push.returncode == 0:
            dispatch_catalog_publish(repository)
            return reply + " A signed catalogue refresh has been queued."
        print(f"Community request push attempt {attempt} raced with main: {push.stderr.strip()}")
    raise SystemExit("Could not save the Marketplace community request after three attempts.")



def process_moderator_command(event):
    issue = event.get("issue") or {}
    comment = event.get("comment") or {}
    number = int(issue.get("number") or 0)
    login = str((comment.get("user") or {}).get("login") or "").strip()
    body = str(comment.get("body") or "").strip()
    if not number or not body.startswith("/"):
        return False
    if login.casefold() not in trusted_reviewers():
        return False

    parts = body.split(maxsplit=3)
    command = parts[0].casefold()
    repository = os.environ["GITHUB_REPOSITORY"]
    now = datetime.now(timezone.utc).isoformat()

    if command in {"/hide-review", "/restore-review"}:
        if len(parts) < 3 or not PACKAGE_ID.fullmatch(parts[1].lower()) or not parts[2].isdigit():
            reply = "Usage: /hide-review <package-id> <review-user-id> or /restore-review <package-id> <review-user-id>."
        else:
            package_id, review_user_id = parts[1].lower(), int(parts[2])
            path = Path("moderation/reviews.json")
            def update(data):
                review = next((item for item in data.get("reviews", []) if item.get("packageId") == package_id and item.get("userId") == review_user_id), None)
                if review is None:
                    raise ValueError("That review does not exist.")
                visibility = "hidden" if command == "/hide-review" else "visible"
                review["moderationStatus"] = visibility
                review["moderatedAt"] = now
                review["moderatedBy"] = login
                return True, f"Review {package_id}/{review_user_id} is now {visibility}."
            reply = persist_json_update(path, update, f"{command[1:]} Marketplace review {package_id}")
    elif command in {"/quarantine", "/restore-package"}:
        if len(parts) < 3 or not PACKAGE_ID.fullmatch(parts[1].lower()) or not SEMVER.fullmatch(parts[2]):
            reply = "Usage: /quarantine <package-id> <version> [reason] or /restore-package <package-id> <version>."
        else:
            package_id, version = parts[1].lower(), parts[2]
            path = Path("moderation/decisions.json")
            def update(data):
                records = data.setdefault("quarantinedPackages", [])
                if command == "/quarantine":
                    reason = parts[3].strip() if len(parts) > 3 else "Under moderator review"
                    current = next((item for item in records if item.get("id") == package_id and item.get("version") == version), None)
                    record = {"id": package_id, "version": version, "reason": reason[:300], "quarantinedAt": now, "quarantinedBy": login}
                    if current:
                        records[records.index(current)] = record
                    else:
                        records.append(record)
                    return True, f"Package {package_id}@{version} has been quarantined. Existing installs are unchanged."
                new_records = [item for item in records if not (item.get("id") == package_id and item.get("version") == version)]
                if len(new_records) == len(records):
                    return False, f"Package {package_id}@{version} was not quarantined."
                data["quarantinedPackages"] = new_records
                return True, f"Package {package_id}@{version} has been restored to the catalogue."
            reply = persist_json_update(path, update, f"{command[1:]} Marketplace package {package_id}@{version}")
    elif command in {"/suspend-publisher", "/unsuspend-publisher"}:
        if len(parts) != 2 or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", parts[1]):
            reply = "Usage: /suspend-publisher <github-login> or /unsuspend-publisher <github-login>."
        else:
            publisher = parts[1].casefold()
            path = Path("moderation/suspended-publishers.json")
            def update(data):
                names = data.setdefault("suspendedPublishers", [])
                existing = {str(value).casefold() for value in names}
                if command == "/suspend-publisher":
                    if publisher in existing:
                        return False, f"Publisher @{parts[1]} is already suspended."
                    names.append(parts[1])
                    return True, f"Publisher @{parts[1]} is suspended. Their packages will be excluded from the next signed catalogue."
                filtered = [value for value in names if str(value).casefold() != publisher]
                if len(filtered) == len(names):
                    return False, f"Publisher @{parts[1]} was not suspended."
                data["suspendedPublishers"] = filtered
                return True, f"Publisher @{parts[1]} is no longer suspended."
            reply = persist_json_update(path, update, f"{command[1:]} Marketplace publisher {parts[1]}")
    else:
        return False

    api("POST", f"/repos/{repository}/issues/{number}/comments", {"body": reply})
    return True


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    if event.get("comment"):
        if process_moderator_command(event):
            return
        print("Issue comment is not an authorized Marketplace moderation command.")
        return
    issue = event.get("issue") or {}
    if issue.get("pull_request"):
        return
    number = int(issue.get("number") or 0)
    author = issue.get("user") or {}
    login = str(author.get("login") or "").strip()
    user_id = author.get("id")
    body = issue.get("body") or ""
    issue_url = str(issue.get("html_url") or "")
    if not number or not login or not issue_url:
        raise SystemExit("Community request issue is missing its number, author, or URL.")

    if RATING_MARKER in body:
        try:
            request = parse_request(body, RATING_MARKER)
            package_id = str(request.get("packageId", "")).strip().lower()
            stars = request.get("stars")
            if not PACKAGE_ID.fullmatch(package_id):
                raise ValueError("The package ID is invalid.")
            if type(stars) is not int or not 1 <= stars <= 5:
                raise ValueError("Choose a star rating from 1 to 5.")
            if type(user_id) is not int or user_id <= 0:
                raise ValueError("GitHub did not provide a valid account ID.")
            found = package_manifests(package_id)
            if not found:
                raise ValueError(f"Package {package_id} does not exist.")
            publisher = str(found[0][1].get("publisher", "")).casefold()
            if publisher == login.casefold():
                raise ValueError("Publishers cannot rate their own packages.")
            if any(str(manifest.get("category", "")).casefold() in {"theme", "themes"} for _, manifest in found):
                raise ValueError("Theme packages are not part of the Marketplace.")
        except Exception as exc:
            finish_issue(repository, number, f"Rating rejected: {exc}")
            return

        path = Path("moderation/ratings.json")
        message = None
        for attempt in range(1, 4):
            subprocess.run(["git", "fetch", "origin", "main"], check=True)
            subprocess.run(["git", "reset", "--hard", "origin/main"], check=True)
            if not package_manifests(package_id):
                finish_issue(repository, number, f"Rating rejected: package {package_id} no longer exists.")
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            ratings = data.setdefault("ratings", [])
            if not isinstance(ratings, list):
                raise SystemExit("moderation/ratings.json ratings must be an array.")
            existing = next(
                (item for item in ratings if item.get("packageId") == package_id and int(item.get("userId", -1)) == user_id),
                None,
            )
            if existing and existing.get("requestUrl") == issue_url:
                message = f"Your {stars}-star rating for {package_id} was already recorded."
                break
            record = {
                "packageId": package_id,
                "userId": user_id,
                "stars": stars,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "requestUrl": issue_url,
            }
            if existing:
                ratings[ratings.index(existing)] = record
                commit_message = f"Update Marketplace rating for {package_id}"
            else:
                ratings.append(record)
                commit_message = f"Record Marketplace rating for {package_id}"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            configure_bot()
            subprocess.run(["git", "add", "--", str(path)], check=True)
            if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
                message = f"Your {stars}-star rating for {package_id} is already current."
                break
            subprocess.run(["git", "commit", "-m", commit_message], check=True)
            push = subprocess.run(["git", "push", "origin", "HEAD:main"], text=True, capture_output=True)
            if push.returncode == 0:
                dispatch_catalog_publish(repository)
                message = f"Your {stars}-star rating for {package_id} has been recorded. A signed catalogue refresh has been queued."
                break
            print(f"Rating push attempt {attempt} raced with another main update: {push.stderr.strip()}")
        if message is None:
            raise SystemExit("Could not save the rating after three attempts.")
        finish_issue(repository, number, message)
        return

    if FEATURE_MARKER in body:
        try:
            request = parse_request(body, FEATURE_MARKER)
            package_id = str(request.get("packageId", "")).strip().lower()
            featured = request.get("featured")
            if not PACKAGE_ID.fullmatch(package_id):
                raise ValueError("The package ID is invalid.")
            if type(featured) is not bool:
                raise ValueError("The featured value must be true or false.")
            if login.casefold() not in trusted_reviewers():
                raise PermissionError("Only trusted Marketplace maintainers can feature or unfeature packages.")
            if not package_manifests(package_id):
                raise ValueError(f"Package {package_id} does not exist.")
        except Exception as exc:
            finish_issue(repository, number, f"Featured-package request rejected: {exc}")
            return

        path = Path("moderation/featured-packages.json")
        message = None
        for attempt in range(1, 4):
            subprocess.run(["git", "fetch", "origin", "main"], check=True)
            subprocess.run(["git", "reset", "--hard", "origin/main"], check=True)
            if not package_manifests(package_id):
                finish_issue(repository, number, f"Featured-package request rejected: {package_id} no longer exists.")
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            packages = data.setdefault("packages", [])
            if not isinstance(packages, list):
                raise SystemExit("moderation/featured-packages.json packages must be an array.")
            current = next((item for item in packages if item.get("id") == package_id), None)
            if current and current.get("requestUrl") == issue_url:
                message = f"Featured status for {package_id} was already processed."
                break
            if featured:
                record = {
                    "id": package_id,
                    "featuredAt": datetime.now(timezone.utc).isoformat(),
                    "featuredBy": login,
                    "requestUrl": issue_url,
                }
                if current:
                    packages[packages.index(current)] = record
                else:
                    packages.append(record)
                reply = f"Package {package_id} has been featured in the Marketplace."
            else:
                data["packages"] = [item for item in packages if item.get("id") != package_id]
                reply = f"Package {package_id} is no longer featured."
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            configure_bot()
            subprocess.run(["git", "add", "--", str(path)], check=True)
            if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
                message = reply
                break
            subprocess.run(["git", "commit", "-m", ("Feature" if featured else "Unfeature") + f" Marketplace package {package_id}"], check=True)
            push = subprocess.run(["git", "push", "origin", "HEAD:main"], text=True, capture_output=True)
            if push.returncode == 0:
                dispatch_catalog_publish(repository)
                message = reply + " A signed catalogue refresh has been queued."
                break
            print(f"Feature push attempt {attempt} raced with another main update: {push.stderr.strip()}")
        if message is None:
            raise SystemExit("Could not update featured packages after three attempts.")
        finish_issue(repository, number, message)
        return

    if REVIEW_MARKER in body:
        try:
            request = parse_request(body, REVIEW_MARKER)
            package_id = str(request.get("packageId", "")).strip().lower()
            title = str(request.get("title", "")).strip()
            review_text = str(request.get("body", "")).strip()
            if not PACKAGE_ID.fullmatch(package_id):
                raise ValueError("The package ID is invalid.")
            if type(user_id) is not int or user_id <= 0:
                raise ValueError("GitHub did not provide a valid account ID.")
            found = package_manifests(package_id)
            if not found:
                raise ValueError("That package no longer exists.")
            publisher = str(found[0][1].get("publisher", "")).casefold()
            if publisher == login.casefold():
                raise ValueError("Publishers cannot review their own packages.")
            if not title or len(title) > 100:
                raise ValueError("A review title is required and must be 100 characters or fewer.")
            if not review_text or len(review_text) > 1200:
                raise ValueError("A review must contain 1–1,200 characters.")
            if EMAIL.search(title + "\n" + review_text) or PHONE.search(title + "\n" + review_text) or SECRET.search(title + "\n" + review_text):
                raise ValueError("Reviews cannot contain contact details or credential-like information.")
        except Exception as exc:
            finish_issue(repository, number, f"Review rejected: {exc}")
            return
        path = Path("moderation/reviews.json")
        now = datetime.now(timezone.utc).isoformat()
        def update(data):
            reviews = data.setdefault("reviews", [])
            existing = next((item for item in reviews if item.get("packageId") == package_id and int(item.get("userId", -1)) == user_id), None)
            record = {
                "packageId": package_id, "userId": user_id, "author": login,
                "title": title, "body": review_text,
                "createdAt": existing.get("createdAt", now) if existing else now,
                "updatedAt": now,
                "helpfulUserIds": existing.get("helpfulUserIds", []) if existing else [],
                "reporterUserIds": existing.get("reporterUserIds", []) if existing else [],
                "reportReasons": existing.get("reportReasons", []) if existing else [],
                "moderationStatus": existing.get("moderationStatus", "visible") if existing else "visible",
                "publisherResponse": existing.get("publisherResponse") if existing else None,
                "requestUrl": issue_url,
            }
            if existing:
                reviews[reviews.index(existing)] = record
                return True, f"Your review for {package_id} was updated."
            reviews.append(record)
            return True, f"Your review for {package_id} was published."
        try:
            reply = persist_json_update(path, update, f"Publish Marketplace review for {package_id}")
            finish_issue(repository, number, reply)
        except Exception as exc:
            finish_issue(repository, number, f"Review rejected: {exc}")
        return

    if HELPFUL_MARKER in body:
        try:
            request = parse_request(body, HELPFUL_MARKER)
            package_id = str(request.get("packageId", "")).strip().lower()
            review_user_id = request.get("reviewUserId")
            if not PACKAGE_ID.fullmatch(package_id) or type(user_id) is not int or user_id <= 0:
                raise ValueError("The package or account reference is invalid.")
            if type(review_user_id) is not int or review_user_id <= 0:
                raise ValueError("The review reference is invalid.")
            if not package_manifests(package_id):
                raise ValueError("That package no longer exists.")
        except Exception as exc:
            finish_issue(repository, number, f"Helpful vote rejected: {exc}")
            return
        path = Path("moderation/reviews.json")
        def update(data):
            review = next((item for item in data.get("reviews", []) if item.get("packageId") == package_id and item.get("userId") == review_user_id), None)
            if review is None:
                raise ValueError("That review no longer exists.")
            if review_user_id == user_id:
                raise ValueError("You cannot vote your own review as helpful.")
            voters = review.setdefault("helpfulUserIds", [])
            if user_id in voters:
                return False, "You have already marked this review helpful."
            voters.append(user_id)
            return True, f"Your helpful vote for {package_id} was recorded."
        try:
            reply = persist_json_update(path, update, f"Record helpful Marketplace review vote for {package_id}")
            finish_issue(repository, number, reply)
        except Exception as exc:
            finish_issue(repository, number, f"Helpful vote rejected: {exc}")
        return

    if PUBLISHER_RESPONSE_MARKER in body:
        try:
            request = parse_request(body, PUBLISHER_RESPONSE_MARKER)
            package_id = str(request.get("packageId", "")).strip().lower()
            review_user_id = request.get("reviewUserId")
            response_text = str(request.get("response", "")).strip()
            if not PACKAGE_ID.fullmatch(package_id) or type(user_id) is not int or user_id <= 0:
                raise ValueError("The package or account reference is invalid.")
            if type(review_user_id) is not int or review_user_id <= 0:
                raise ValueError("The review reference is invalid.")
            if not response_text or len(response_text) > 800:
                raise ValueError("A publisher response must contain 1–800 characters.")
            if EMAIL.search(response_text) or PHONE.search(response_text) or SECRET.search(response_text):
                raise ValueError("Responses cannot contain contact details or credential-like information.")
            found = package_manifests(package_id)
            if not found:
                raise ValueError("That package no longer exists.")
            publishers = {str(manifest.get("publisher", "")).casefold() for _, manifest in found}
            if login.casefold() not in publishers:
                raise ValueError("Only this package's publisher can respond to reviews.")
        except Exception as exc:
            finish_issue(repository, number, f"Publisher response rejected: {exc}")
            return
        path = Path("moderation/reviews.json")
        now = datetime.now(timezone.utc).isoformat()
        def update(data):
            review = next((item for item in data.get("reviews", []) if item.get("packageId") == package_id and item.get("userId") == review_user_id), None)
            if review is None:
                raise ValueError("That review no longer exists.")
            if review.get("moderationStatus") == "hidden":
                raise ValueError("A hidden review cannot receive a public publisher response.")
            review["publisherResponse"] = {"author": login, "body": response_text, "updatedAt": now}
            return True, f"Your response to the review on {package_id} was saved."
        try:
            reply = persist_json_update(path, update, f"Publish Marketplace response for {package_id}")
            finish_issue(repository, number, reply)
        except Exception as exc:
            finish_issue(repository, number, f"Publisher response rejected: {exc}")
        return

    if REVIEW_REPORT_MARKER in body:
        try:
            request = parse_request(body, REVIEW_REPORT_MARKER)
            package_id = str(request.get("packageId", "")).strip().lower()
            review_user_id = request.get("reviewUserId")
            reason = str(request.get("reason", "")).strip().lower()
            allowed_reasons = {"spam", "harassment", "misinformation", "unsafe", "other"}
            if not PACKAGE_ID.fullmatch(package_id) or type(user_id) is not int or user_id <= 0:
                raise ValueError("The package or account reference is invalid.")
            if type(review_user_id) is not int or review_user_id <= 0 or reason not in allowed_reasons:
                raise ValueError("Choose a valid review and report reason.")
            if not package_manifests(package_id):
                raise ValueError("That package no longer exists.")
        except Exception as exc:
            finish_issue(repository, number, f"Review report rejected: {exc}")
            return
        path = Path("moderation/reviews.json")
        now = datetime.now(timezone.utc).isoformat()
        def update(data):
            review = next((item for item in data.get("reviews", []) if item.get("packageId") == package_id and item.get("userId") == review_user_id), None)
            if review is None:
                raise ValueError("That review no longer exists.")
            if review_user_id == user_id:
                raise ValueError("You cannot report your own review.")
            reporters = review.setdefault("reporterUserIds", [])
            if user_id in reporters:
                return False, "You have already reported this review."
            reporters.append(user_id)
            review.setdefault("reportReasons", []).append({"reason": reason, "reportedAt": now})
            if len(set(reporters)) >= 3 and review.get("moderationStatus", "visible") == "visible":
                review["moderationStatus"] = "under_review"
                review["underReviewAt"] = now
            return True, f"Your report for {package_id} was sent to moderation. The review will be temporarily hidden after three independent reports."
        try:
            reply = persist_json_update(path, update, f"Report Marketplace review for {package_id}")
            finish_issue(repository, number, reply)
        except Exception as exc:
            finish_issue(repository, number, f"Review report rejected: {exc}")
        return

    if DOWNLOAD_MARKER in body:
        try:
            request = parse_request(body, DOWNLOAD_MARKER)
            package_id = str(request.get("packageId", "")).strip().lower()
            version = str(request.get("version", "")).strip()
            found = package_manifests(package_id) if PACKAGE_ID.fullmatch(package_id) else []
            if type(user_id) is not int or user_id <= 0 or not SEMVER.fullmatch(version):
                raise ValueError("The package version or account reference is invalid.")
            if not any(manifest.get("version") == version for _, manifest in found):
                raise ValueError("That package version is not published.")
        except Exception as exc:
            finish_issue(repository, number, f"Download statistic rejected: {exc}")
            return
        path = Path("moderation/download-stats.json")
        day = datetime.now(timezone.utc).date().isoformat()
        def update(data):
            packages = data.setdefault("packages", {})
            stats = packages.setdefault(package_id, {"totalDownloads": 0, "uniqueUserIds": [], "daily": []})
            daily = next((item for item in stats.setdefault("daily", []) if item.get("date") == day), None)
            if daily is None:
                daily = {"date": day, "count": 0, "userIds": []}
                stats["daily"].append(daily)
            if user_id in daily.setdefault("userIds", []):
                return False, f"Your install of {package_id} has already been counted today."
            daily["userIds"].append(user_id)
            daily["count"] = int(daily.get("count", 0)) + 1
            stats["totalDownloads"] = int(stats.get("totalDownloads", 0)) + 1
            if user_id not in stats.setdefault("uniqueUserIds", []):
                stats["uniqueUserIds"].append(user_id)
            return True, f"Your install of {package_id} was counted in Marketplace statistics."
        try:
            reply = persist_json_update(path, update, f"Update Marketplace download stats for {package_id}")
            finish_issue(repository, number, reply)
        except Exception as exc:
            finish_issue(repository, number, f"Download statistic rejected: {exc}")
        return

    print("Issue is not an OpenTasker Marketplace community request.")


if __name__ == "__main__":
    main()
