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


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
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
                message = f"Your {stars}-star rating for {package_id} has been recorded. The Marketplace summary will update after the signed catalogue refreshes."
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
                message = reply + " The signed catalogue will show the change after it refreshes."
                break
            print(f"Feature push attempt {attempt} raced with another main update: {push.stderr.strip()}")
        if message is None:
            raise SystemExit("Could not update featured packages after three attempts.")
        finish_issue(repository, number, message)
        return

    print("Issue is not an OpenTasker Marketplace rating or feature request.")


if __name__ == "__main__":
    main()
