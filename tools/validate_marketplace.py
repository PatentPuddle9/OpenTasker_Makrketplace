#!/usr/bin/env python3
"""Fail-closed validator for data-only OpenTasker marketplace packages."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import zlib
from pathlib import Path
from urllib.parse import urlsplit

PACKAGE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")
INPUT_TOKEN = re.compile(r"^\{\{input:([A-Za-z][A-Za-z0-9_-]{0,47})\}\}$")
INPUT_REFERENCE = re.compile(r"\{\{input:([A-Za-z][A-Za-z0-9_-]{0,47})\}\}")
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
US_PHONE = re.compile(r"(?<!\w)(?:\+?1[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]?\d{4}(?!\w)")
SECRET_VALUE = re.compile(r"(?i)\b(?:bearer\s+[A-Za-z0-9._~+/=-]{12,}|(?:sk|gh[pousr]?)_[A-Za-z0-9_-]{16,}|(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*['\"]?[^\s,'\"]{8,})")
SENSITIVE_KEY = re.compile(r"(?i)(phone|recipient|contact|email|address|authorization|token|secret|password|credential|api.?key|webhook.?secret|sms.?to|destination.?number)")
PACKAGE_ASSET_REFERENCE = re.compile(r"\{\{asset:(asset-(?:0[1-9]|1[0-2]))}}")
PACKAGE_ASSET_FILE = re.compile(r"^assets/(?P<stem>image|audio)-(?P<number>0[1-9]|1[0-2])\.(?P<extension>png|mp3|ogg|wav|m4a)$")

HIGH_RISK_ACTIONS = {
    "sms.send", "contacts.lookup", "lock", "screen.off", "reboot",
    "settings.write", "app.archive", "app.unarchive", "http.request",
    "http.get", "http.post", "integration.home_assistant.webhook",
    "mqtt.publish", "download", "plugin.locale.fire", "plugin.locale.query",
    "auth.device_credential", "script.run", "file.delete", "file.write",
    "vpn.enable", "vpn.disable", "clipboard.set",
}
MEDIUM_RISK_ACTIONS = {
    "clipboard.get", "file.read", "file.list", "notify.send", "notify.cancel",
    "brightness.set", "volume.set", "torch.set", "dnd.set", "zen.rule.set",
    "zen.rule.clear", "ringer.set", "wifi.scan", "screenshot.take",
    "app.launch", "intent.launch", "file.append",
}
EXTERNAL_ACTIONS = {
    "http.request", "http.get", "http.post",
    "integration.home_assistant.webhook", "mqtt.publish", "download",
}
FORBIDDEN_ACTIONS = {
    "shell.exec", "shell.run", "javascript.eval", "code.execute",
    "native.execute", "arbitrary.script", "apk.install.silent",
}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

KNOWN_ACTIONS = {
    "widget.display.control", "var.set", "var.persist", "clipboard.get", "clipboard.set",
    "data.read", "brightness.read", "volume.read", "torch.read", "datetime.format",
    "datetime.parse", "datetime.add", "text.match", "text.replace", "text.split", "text.join",
    "text.substring", "flow.wait", "task.run", "flow.if", "flow.else", "flow.endif",
    "flow.foreach", "flow.endfor", "flow.try", "flow.catch", "flow.endtry", "flow.stop",
    "intent.launch", "app.launch", "shortcut.publish", "home.go", "url.open", "file.read",
    "file.write", "file.append", "file.delete", "file.list", "http.request", "http.get",
    "http.post", "integration.home_assistant.webhook", "mqtt.publish", "ping", "download",
    "vibrate", "toast.show", "log", "notify.show", "notify.send", "notify.cancel",
    "notify.progress", "contacts.lookup", "plugin.locale.fire", "plugin.locale.query",
    "wifi.toggle", "bluetooth.toggle", "brightness.set", "screen.timeout", "settings.write",
    "app.kill", "app.archive", "app.unarchive", "wol", "volume.set", "dnd.set",
    "zen.rule.set", "zen.rule.clear", "ringer.set", "torch.set", "airplane.toggle",
    "mobile.toggle", "aod.set", "wifi.scan", "sms.send", "screenshot.take", "sound.play",
    "sound.stop", "sound.pause", "track.next", "track.previous", "media.mute", "tts.speak",
    "reboot", "lock", "tile.set", "state.temporary", "ime.info", "ime.set", "screen.off",
    "wake", "tasker.unsupported", "macrodroid.unsupported", "scene.show", "var.clear",
    "var.convert", "array.set", "array.get", "array.push", "array.remove", "popup.show",
}


def iter_strings(value, path="$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from iter_strings(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_strings(child, f"{path}/{index}")
    elif isinstance(value, str):
        yield path, value


def resolve_pointer(document, pointer):
    if not pointer.startswith("/"):
        raise ValueError(f"Input path must be a JSON Pointer: {pointer}")
    current = document
    for raw in pointer[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        current = current[int(key)] if isinstance(current, list) else current[key]
    return current


def action_rows(bundle):
    rows = []
    for ti, task in enumerate(bundle.get("tasks", [])):
        for ai, action in enumerate(task.get("actions", [])):
            rows.append((action.get("type", ""), action, f"/tasks/{ti}/actions/{ai}"))
    return rows


def is_private_host(host):
    if host in LOCAL_HOSTS or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_private or address.is_loopback or address.is_link_local
    except ValueError:
        return False


def external_hosts(bundle):
    found = set()
    for path, value in iter_strings(bundle):
        if not value.lower().startswith(("https://", "http://")):
            continue
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if host and not is_private_host(host):
            found.add(host)
        if parsed.username or parsed.password:
            raise ValueError(f"Credentials embedded in URL at {path}; move them to a local input.")
        if parsed.query and re.search(r"(?i)(token|key|secret|auth|password|code)=", parsed.query):
            raise ValueError(f"Credential-like query parameter found in URL at {path}.")
        if parsed.path and re.search(r"(?i)/(?:webhook|token|secret|key)/[^/]{12,}(?:/|$)", parsed.path):
            raise ValueError(f"Credential-like path segment found in URL at {path}.")
        if parsed.scheme.lower() == "http" and host and not is_private_host(host):
            raise ValueError(f"External destination at {path} must use HTTPS.")
    return found


def validate_png(path: Path, max_bytes: int, label: str, max_dimension: int = 2048):
    if not path.is_file():
        return [f"{label} is missing."]
    size = path.stat().st_size
    if size < 45 or size > max_bytes:
        return [f"{label} must be a PNG between 45 bytes and {max_bytes} bytes."]
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return [f"{label} must be a valid PNG image."]

    # Accept only ordinary image chunks. Text, EXIF, timestamps, and embedded color
    # profiles are unnecessary for Marketplace previews and can carry private metadata.
    allowed_chunks = {
        b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA",
        b"cHRM", b"sRGB", b"sBIT", b"bKGD", b"pHYs",
    }
    offset = 8
    width = height = 0
    saw_header = saw_data = saw_end = False
    while offset + 12 <= len(data):
        chunk_length = int.from_bytes(data[offset:offset + 4], "big")
        chunk_type = data[offset + 4:offset + 8]
        chunk_end = offset + 12 + chunk_length
        if chunk_end > len(data):
            return [f"{label} contains a truncated PNG chunk."]
        if chunk_type not in allowed_chunks:
            return [f"{label} contains unsupported or metadata-bearing PNG chunk {chunk_type.decode('ascii', 'replace')}."]
        chunk_payload = data[offset + 8:offset + 8 + chunk_length]
        stored_crc = int.from_bytes(data[offset + 8 + chunk_length:chunk_end], "big")
        calculated_crc = zlib.crc32(chunk_type + chunk_payload) & 0xFFFFFFFF
        if stored_crc != calculated_crc:
            return [f"{label} contains a PNG chunk with an invalid checksum."]

        if not saw_header:
            if chunk_type != b"IHDR" or chunk_length != 13:
                return [f"{label} must begin with a valid PNG IHDR chunk."]
            width = int.from_bytes(chunk_payload[0:4], "big")
            height = int.from_bytes(chunk_payload[4:8], "big")
            bit_depth = chunk_payload[8]
            color_type = chunk_payload[9]
            compression = chunk_payload[10]
            filtering = chunk_payload[11]
            interlace = chunk_payload[12]
            if width < 1 or height < 1 or width > max_dimension or height > max_dimension:
                return [f"{label} dimensions must be between 1 and {max_dimension} pixels."]
            if bit_depth not in {1, 2, 4, 8, 16} or color_type not in {0, 2, 3, 4, 6}:
                return [f"{label} uses an unsupported PNG color format."]
            if compression != 0 or filtering != 0 or interlace not in {0, 1}:
                return [f"{label} uses unsupported PNG compression, filtering, or interlacing."]
            saw_header = True
        elif chunk_type == b"IHDR":
            return [f"{label} contains more than one IHDR chunk."]

        if chunk_type == b"IDAT":
            if saw_end:
                return [f"{label} contains image data after its end marker."]
            saw_data = True
        elif chunk_type == b"IEND":
            if chunk_length != 0 or not saw_data:
                return [f"{label} has an invalid PNG end marker."]
            saw_end = True
            offset = chunk_end
            break
        offset = chunk_end

    if not (saw_header and saw_data and saw_end) or offset != len(data):
        return [f"{label} is incomplete or contains trailing data after IEND."]
    return []


def validate_package_assets(folder: Path, manifest: dict, payload: dict):
    errors = []
    assets = manifest.get("assets", [])
    if not isinstance(assets, list):
        return ["assets must be a list of at most 12 optional package media files."]
    if len(assets) > 12:
        errors.append("assets may contain at most 12 optional package media files.")

    category = str(manifest.get("category", ""))
    if assets and category not in {"Actions", "Shortcut Widgets", "Widget Displays"}:
        errors.append("Only Action, Shortcut Widget, and Widget Display packages may include bundled media.")
    if category == "Custom Widget Icons" and assets:
        errors.append("Custom Widget Icon packages use icon.png and cannot declare additional media assets.")

    seen_keys = set()
    seen_files = set()
    declared_keys = set()
    total_bytes = 0
    for index, asset in enumerate(assets[:12]):
        label = f"package asset {index + 1}"
        if not isinstance(asset, dict):
            errors.append(f"{label} must be an object.")
            continue

        key = str(asset.get("key", ""))
        path = str(asset.get("file", ""))
        match = PACKAGE_ASSET_FILE.fullmatch(path)
        if not re.fullmatch(r"asset-(?:0[1-9]|1[0-2])", key):
            errors.append(f"{label} has an invalid key.")
            continue
        if key in seen_keys:
            errors.append(f"Duplicate package asset key: {key}.")
        seen_keys.add(key)
        declared_keys.add(key)
        if not match:
            errors.append(f"{label} has an unsupported file path.")
            continue
        stem = match.group("stem")
        number = match.group("number")
        extension = match.group("extension")
        if key != f"asset-{number}":
            errors.append(f"{label} key and filename numbers must match.")
        if path in seen_files:
            errors.append(f"Duplicate package asset file: {path}.")
        seen_files.add(path)

        expected_type = {
            "png": "image/png",
            "mp3": "audio/mpeg",
            "ogg": "audio/ogg",
            "wav": "audio/wav",
            "m4a": "audio/mp4",
        }[extension]
        media_type = str(asset.get("mediaType", ""))
        if media_type != expected_type or (stem == "image" and extension != "png") or (stem == "audio" and extension == "png"):
            errors.append(f"{label} mediaType does not match its supported file type.")
            continue
        if category == "Widget Displays" and media_type != "image/png":
            errors.append(f"{label}: Widget Display packages may bundle images, not audio.")

        size_declared = asset.get("sizeBytes")
        if type(size_declared) is not int or not 1 <= size_declared <= 10 * 1024 * 1024:
            errors.append(f"{label} sizeBytes must be between 1 byte and 10 MB.")
            continue
        digest = str(asset.get("sha256", ""))
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            errors.append(f"{label} sha256 must be a lowercase SHA-256 digest.")
            continue

        file_path = folder / path
        if file_path.is_symlink() or not file_path.is_file():
            errors.append(f"{label} file is missing or is not a regular file.")
            continue
        try:
            resolved_folder = folder.resolve()
            resolved_file = file_path.resolve()
            if resolved_folder not in resolved_file.parents:
                errors.append(f"{label} resolves outside its package directory.")
                continue
            raw = file_path.read_bytes()
        except OSError as exc:
            errors.append(f"{label} could not be read: {exc}.")
            continue

        if len(raw) != size_declared:
            errors.append(f"{label} sizeBytes does not match the actual file size.")
            continue
        total_bytes += len(raw)
        if total_bytes > 40 * 1024 * 1024:
            errors.append("Combined package media files may not exceed 40 MB.")
            break
        if hashlib.sha256(raw).hexdigest() != digest:
            errors.append(f"{label} checksum does not match sha256 in manifest.json.")

        if media_type == "image/png":
            errors.extend(validate_png(file_path, 5 * 1024 * 1024, path))
        elif media_type == "audio/mpeg":
            valid_audio = raw.startswith(b"ID3") or (
                len(raw) >= 2 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0
            )
            if not valid_audio:
                errors.append(f"{label} is not a recognizable MP3 audio file.")
        elif media_type == "audio/ogg" and not raw.startswith(b"OggS"):
            errors.append(f"{label} is not a recognizable OGG audio file.")
        elif media_type == "audio/wav" and not (raw.startswith(b"RIFF") and raw[8:12] == b"WAVE"):
            errors.append(f"{label} is not a recognizable WAV audio file.")
        elif media_type == "audio/mp4" and not (len(raw) >= 12 and raw[4:8] == b"ftyp"):
            errors.append(f"{label} is not a recognizable M4A audio file.")

    referenced_keys = set()
    for value_path, value in iter_strings(payload):
        matches = PACKAGE_ASSET_REFERENCE.findall(value)
        referenced_keys.update(matches)
        if "{{asset:" in value and "{{asset:" in PACKAGE_ASSET_REFERENCE.sub("", value):
            errors.append(f"malformed package asset reference at {value_path}.")
        if value.strip().lower().startswith(("content://", "file://")):
            errors.append(f"device-local file URI is not portable package content at {value_path}.")
    undeclared = referenced_keys - declared_keys
    if undeclared:
        errors.append("bundle contains undeclared package asset references: " + ", ".join(sorted(undeclared)))
    return errors


def validate_visual_package(folder: Path, manifest: dict, payload: dict, bundle_path: Path):
    category = str(manifest.get("category", ""))
    errors = []
    errors.extend(validate_package_assets(folder, manifest, payload))
    preview_file = manifest.get("previewFile")
    if preview_file != "preview.png":
        errors.append("visual Marketplace packages must include previewFile=preview.png.")
    errors.extend(validate_png(folder / "preview.png", 2 * 1024 * 1024, "preview.png"))
    if manifest.get("requiredInputs", []) not in ([], None):
        errors.append("visual Marketplace packages cannot declare automation setup inputs.")
    if manifest.get("externalDestinations", []) not in ([], None):
        errors.append("visual Marketplace packages cannot declare external service destinations.")

    for source_label, source in (("package payload", payload), ("listing metadata", {
        key: manifest.get(key, "")
        for key in ("name", "summary", "description", "changelog", "documentationUrl")
    })):
        for value_path, value in iter_strings(source):
            if EMAIL.search(value) or US_PHONE.search(value) or SECRET_VALUE.search(value):
                errors.append(
                    f"{source_label} contains possible personal information or a credential at {value_path}."
                )

    package_type = payload.get("type")
    expected = {
        "Widget Displays": "widget_display",
        "Custom Widget Icons": "custom_widget_icon",
    }.get(category)
    if package_type != expected or payload.get("schemaVersion") != 1:
        errors.append(f"bundle.json must contain schemaVersion=1 and type={expected!r} for category {category!r}.")
        return {
            "manifest": manifest,
            "bundle": payload,
            "riskLevel": "low",
            "actionIds": [],
            "unknownActionIds": [],
            "bundleSha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
            "errors": errors,
            "warnings": [],
        }

    if category == "Widget Displays":
        config = payload.get("config")
        if not isinstance(config, dict):
            errors.append("Widget Display payload must contain a config object.")
        else:
            states = config.get("states")
            width = config.get("canvasWidthDp")
            height = config.get("canvasHeightDp")
            if not isinstance(width, int) or not 110 <= width <= 1000:
                errors.append("Widget Display canvasWidthDp must be between 110 and 1000.")
            if not isinstance(height, int) or not 80 <= height <= 1000:
                errors.append("Widget Display canvasHeightDp must be between 80 and 1000.")
            if not isinstance(states, list) or not 1 <= len(states) <= 75:
                errors.append("Widget Display must contain between 1 and 75 states.")
            else:
                allowed_elements = {"TEXT", "IMAGE", "BUTTON", "SHORTCUT", "ICON", "PROGRESS", "DIVIDER", "SPACER"}
                for state_index, state in enumerate(states):
                    if not isinstance(state, dict):
                        errors.append(f"Widget Display state {state_index + 1} is invalid.")
                        continue
                    elements = state.get("elements", [])
                    if not isinstance(elements, list) or len(elements) > 8:
                        errors.append(f"Widget Display state {state_index + 1} can contain at most 8 elements.")
                        continue
                    for element_index, element in enumerate(elements):
                        label = f"Widget Display state {state_index + 1} element {element_index + 1}"
                        if not isinstance(element, dict) or element.get("type") not in allowed_elements:
                            errors.append(f"{label} has an unsupported element type.")
                            continue
                        if element.get("actionProfileId") is not None:
                            errors.append(f"{label} must not contain a publisher's local Action reference.")
                        image_uri = str(element.get("imageUri", ""))
                        if image_uri and not PACKAGE_ASSET_REFERENCE.fullmatch(image_uri):
                            errors.append(f"{label} imageUri must use a declared Marketplace asset reference, not a private device URI.")
                        if str(element.get("icon", "")).startswith("custom:"):
                            errors.append(f"{label} references a locally stored custom icon; use a built-in icon so the Widget Display works on other devices.")
                        for key, minimum, maximum in (
                            ("xDp", 0, 1000), ("yDp", 0, 1000),
                            ("widthDp", 1, 1000), ("heightDp", 1, 1000),
                            ("textSizeSp", 1, 96), ("progress", 0, 100),
                        ):
                            value = element.get(key, 0)
                            if not isinstance(value, int) or not minimum <= value <= maximum:
                                errors.append(f"{label} has an invalid {key} value.")
                        if len(str(element.get("text", ""))) > 1000:
                            errors.append(f"{label} text must be 1000 characters or fewer.")
            for state_index, state in enumerate(states if isinstance(states, list) else []):
                if not isinstance(state, dict):
                    continue
                for color_key in ("backgroundColor", "textColor", "accentColor"):
                    color = state.get(color_key)
                    # Android serializes ARGB colors through signed Kotlin Int values.
                    if not isinstance(color, int) or not -0x80000000 <= color <= 0xFFFFFFFF:
                        errors.append(f"Widget Display state {state_index + 1} has an invalid {color_key}.")

    elif category == "Custom Widget Icons":
        if str(payload.get("name", "")).strip() == "" or len(str(payload.get("name", ""))) > 48:
            errors.append("Custom Widget Icon name must be between 1 and 48 characters.")
        if not isinstance(payload.get("recolorable", False), bool):
            errors.append("Custom Widget Icon recolorable must be a boolean.")
        if manifest.get("assetFile") != "icon.png":
            errors.append("Custom Widget Icon package must declare assetFile=icon.png.")
        icon_path = folder / "icon.png"
        errors.extend(validate_png(icon_path, 15 * 1024 * 1024, "icon.png"))
        if icon_path.is_file() and icon_path.stat().st_size >= 24:
            with icon_path.open("rb") as icon_file:
                icon_header = icon_file.read(24)
            if icon_header[:8] == b"\\x89PNG\\r\\n\\x1a\\n" and icon_header[12:16] == b"IHDR":
                icon_width = int.from_bytes(icon_header[16:20], "big")
                icon_height = int.from_bytes(icon_header[20:24], "big")
                if icon_width != icon_height:
                    errors.append("Custom Widget Icon asset must be square.")

    return {
        "manifest": manifest,
        "bundle": payload,
        "riskLevel": "low",
        "actionIds": [],
        "unknownActionIds": [],
        "bundleSha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
        "errors": errors,
        "warnings": [],
    }


def validate_package(folder: Path):
    errors, warnings = [], []
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    bundle_path = folder / "bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    package_id, version = str(manifest.get("id", "")), str(manifest.get("version", ""))

    if not PACKAGE_ID.fullmatch(package_id):
        errors.append("id must be a lowercase package slug.")
    if not SEMVER.fullmatch(version):
        errors.append("version must be semantic versioning.")
    if folder.name != version:
        errors.append("directory must be packages/<package-id>/<version>.")
    if folder.parent.name != package_id:
        errors.append("directory must match manifest package id.")
    if manifest.get("schemaVersion") != 1:
        errors.append("unsupported manifest schemaVersion.")
    if manifest.get("bundleFile") != "bundle.json":
        errors.append("bundleFile must be bundle.json.")
    if not manifest.get("publisher") or not manifest.get("name") or not manifest.get("summary"):
        errors.append("publisher, name, and summary are required.")
    if len(str(manifest.get("summary", ""))) > 400:
        errors.append("summary must be 400 characters or fewer.")

    description = manifest.get("description", "")
    if not isinstance(description, str) or len(description) > 4000:
        errors.append("description must be text with 4000 characters or fewer.")
    tags = manifest.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 10 or any(
        not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _+-]{0,23}", tag)
        for tag in tags
    ):
        errors.append("tags must be a list of up to 10 short, plain-text labels.")
    icon = manifest.get("icon", "bolt")
    if not isinstance(icon, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", icon):
        errors.append("icon must be a built-in icon key.")
    for color_key in ("iconColor", "backgroundColor"):
        color = manifest.get(color_key, "#FFFFFF" if color_key == "iconColor" else "#6750A4")
        if not isinstance(color, str) or not re.fullmatch(r"#?[A-Fa-f0-9]{6}", color):
            errors.append(f"{color_key} must be a six-digit hex color.")
    if not isinstance(manifest.get("gradient", True), bool):
        errors.append("gradient must be a boolean.")
    if manifest.get("shape", "squircle") not in {"squircle", "rounded_square", "circle", "square", "teardrop"}:
        errors.append("shape must be a supported app-icon shape.")
    changelog = manifest.get("changelog", "")
    if not isinstance(changelog, str) or len(changelog) > 2000:
        errors.append("changelog must be text with 2000 characters or fewer.")
    documentation_url = manifest.get("documentationUrl", "")
    if documentation_url:
        parsed_documentation_url = urlsplit(str(documentation_url))
        if parsed_documentation_url.scheme != "https" or not parsed_documentation_url.hostname or parsed_documentation_url.username or parsed_documentation_url.password:
            errors.append("documentationUrl must be a valid HTTPS URL without embedded credentials.")
        if len(str(documentation_url)) > 300:
            errors.append("documentationUrl must be 300 characters or fewer.")

    faqs = manifest.get("faqs", [])
    if not isinstance(faqs, list) or len(faqs) > 10:
        errors.append("faqs must be a list of at most 10 question-and-answer entries.")
    else:
        for index, faq in enumerate(faqs):
            if not isinstance(faq, dict):
                errors.append(f"FAQ {index + 1} must be an object.")
                continue
            question, answer = faq.get("question", ""), faq.get("answer", "")
            if not isinstance(question, str) or not question.strip() or len(question) > 160:
                errors.append(f"FAQ {index + 1} question must be 1–160 characters.")
            if not isinstance(answer, str) or not answer.strip() or len(answer) > 1200:
                errors.append(f"FAQ {index + 1} answer must be 1–1,200 characters.")
    dependencies = manifest.get("dependencies", [])
    if not isinstance(dependencies, list) or len(dependencies) > 10:
        errors.append("dependencies must be a list of at most 10 package requirements.")
    else:
        seen_dependencies = set()
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                errors.append("Each dependency must be an object with id and minimumVersion.")
                continue
            dependency_id = str(dependency.get("id", "")).strip()
            minimum_version = str(dependency.get("minimumVersion", ""))
            if not PACKAGE_ID.fullmatch(dependency_id) or dependency_id == package_id:
                errors.append("Dependency IDs must be valid package IDs and cannot reference the package itself.")
            if dependency_id in seen_dependencies:
                errors.append(f"Duplicate dependency: {dependency_id}.")
            seen_dependencies.add(dependency_id)
            if not SEMVER.fullmatch(minimum_version):
                errors.append(f"Dependency {dependency_id or '(unknown)'} minimumVersion must use semantic versioning.")
            if not isinstance(dependency.get("optional", False), bool):
                errors.append(f"Dependency {dependency_id or '(unknown)'} optional must be a boolean.")
    screenshots = manifest.get("screenshots", [])
    if not isinstance(screenshots, list) or len(screenshots) > 4:
        errors.append("screenshots must list at most 4 PNG files.")
    else:
        seen_screenshots = set()
        for screenshot in screenshots:
            if not isinstance(screenshot, str) or not re.fullmatch(r"screenshots/[0-9]{2}\.png", screenshot):
                errors.append("Screenshot paths must use screenshots/01.png through screenshots/99.png.")
                continue
            if screenshot in seen_screenshots:
                errors.append(f"Duplicate screenshot path: {screenshot}.")
            seen_screenshots.add(screenshot)
            errors.extend(validate_png(folder / screenshot, 2 * 1024 * 1024, screenshot))

    reserved = {"riskLevel", "reviewStatus", "reviewedAt", "reviewedBy", "signature", "moderatorApproval"}
    if reserved.intersection(manifest):
        errors.append("risk and review metadata are computed by the repository, not submitted by package creators.")

    category = str(manifest.get("category", ""))
    if category.strip().casefold() in {"theme", "themes"} or (
        isinstance(bundle, dict)
        and str(bundle.get("type", "")).strip().casefold() == "theme"
    ):
        errors.append("Theme packages are no longer accepted by the OpenTasker Marketplace.")
        return {
            "manifest": manifest,
            "bundle": bundle,
            "riskLevel": "low",
            "actionIds": [],
            "unknownActionIds": [],
            "bundleSha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
            "errors": errors,
            "warnings": warnings,
        }
    if category in {"Widget Displays", "Custom Widget Icons"}:
        return validate_visual_package(folder, manifest, bundle, bundle_path)

    errors.extend(validate_package_assets(folder, manifest, bundle))
    if not isinstance(bundle, dict) or not isinstance(bundle.get("tasks", []), list):
        errors.append("bundle.json must be a valid OpenTasker bundle with a tasks array.")
    if bundle.get("schemaVersion") not in (1, 2):
        errors.append("bundle schemaVersion must be supported by OpenTasker (1 or 2).")
    if any(key in bundle for key in ("scripts", "executables", "binaries", "nativeLibraries")):
        errors.append("executable content is not accepted in marketplace bundles.")

    inputs = manifest.get("requiredInputs", [])
    input_by_key = {}
    for item in inputs:
        key = str(item.get("key", ""))
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,47}", key):
            errors.append(f"invalid required input key: {key}")
            continue
        if key in input_by_key:
            errors.append(f"duplicate required input key: {key}")
        input_by_key[key] = item
        try:
            actual = resolve_pointer(bundle, str(item.get("path", "")))
            if not isinstance(actual, str) or actual != "{{input:" + key + "}}":
                errors.append(f"required input {key} must replace its value with {{{{input:{key}}}}}.")
        except (KeyError, IndexError, ValueError, TypeError):
            errors.append(f"required input {key} points to a missing or invalid bundle field.")

    tokens = set()
    for path, value in iter_strings(bundle):
        tokens.update(INPUT_REFERENCE.findall(value))
        if EMAIL.search(value) or US_PHONE.search(value) or SECRET_VALUE.search(value):
            errors.append(f"possible personal data or credential detected at {path}; replace it with a declared input.")
    undeclared = tokens - set(input_by_key)
    if undeclared:
        errors.append("bundle contains undeclared input placeholders: " + ", ".join(sorted(undeclared)))

    risk, action_ids, unknown_ids = "low", set(), set()
    for action_id, action, action_path in action_rows(bundle):
        if not action_id:
            errors.append(f"action missing type at {action_path}.")
            continue
        action_ids.add(action_id)
        if action_id in FORBIDDEN_ACTIONS:
            errors.append(f"{action_id} is executable-code functionality and cannot be distributed.")
        elif action_id in HIGH_RISK_ACTIONS:
            risk = "high"
        elif action_id in MEDIUM_RISK_ACTIONS and risk == "low":
            risk = "medium"
        elif action_id not in KNOWN_ACTIONS:
            unknown_ids.add(action_id)
            risk = "high"
        args = action.get("args", {})
        if isinstance(args, dict):
            for key, value in args.items():
                if isinstance(value, str) and SENSITIVE_KEY.search(str(key)):
                    if not INPUT_TOKEN.fullmatch(value) and not value.strip().startswith(("%", "{{")):
                        errors.append(f"sensitive field {action_path}/args/{key} must be a local input, not a bundled value.")

    destinations = manifest.get("externalDestinations", [])
    declared_domains = {str(item.get("domain", "")).lower().rstrip(".") for item in destinations}
    try:
        found_hosts = external_hosts(bundle)
        undeclared_hosts = {
            host for host in found_hosts
            if not any(host == domain or host.endswith("." + domain) for domain in declared_domains if domain)
        }
        if undeclared_hosts:
            errors.append("bundle contacts undeclared external destinations: " + ", ".join(sorted(undeclared_hosts)))
    except ValueError as exc:
        errors.append(str(exc))

    if action_ids.intersection(EXTERNAL_ACTIONS) and not destinations:
        errors.append("network, SMS, webhook, and MQTT actions require externalDestinations declarations.")
    for item in destinations:
        domain = str(item.get("domain", "")).lower().rstrip(".")
        if not domain or "/" in domain or "@" in domain or " " in domain:
            errors.append("external destination domain must be a hostname only.")
        if not item.get("provider") or not item.get("purpose") or not item.get("dataFields"):
            errors.append(f"external destination {domain or '(unknown)'} needs provider, purpose, and dataFields.")
        if not item.get("hostingCountry"):
            errors.append(f"external destination {domain or '(unknown)'} must state a hosting country or Unknown.")
        if not str(item.get("privacyPolicyUrl", "")).startswith("https://"):
            errors.append(f"external destination {domain or '(unknown)'} needs an HTTPS privacyPolicyUrl.")
        if item.get("privacyAssessment") not in {"verified", "not-verified", "known-concerns"}:
            errors.append(f"external destination {domain or '(unknown)'} needs a privacyAssessment.")

    if unknown_ids:
        warnings.append("Unclassified action IDs are high risk and may be blocked by OpenTasker's local capability checks: " + ", ".join(sorted(unknown_ids)))

    return {
        "manifest": manifest,
        "bundle": bundle,
        "riskLevel": risk,
        "actionIds": sorted(action_ids),
        "unknownActionIds": sorted(unknown_ids),
        "bundleSha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
        "errors": errors,
        "warnings": warnings,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("folders", nargs="*", default=["packages"])
    args = parser.parse_args()
    failed = False
    for base in args.folders:
        root = Path(base)
        if not root.exists():
            continue
        for manifest_path in sorted(root.glob("*/*/manifest.json")):
            folder = manifest_path.parent
            try:
                result = validate_package(folder)
                for message in result["errors"]:
                    print(f"ERROR {folder}: {message}")
                for message in result["warnings"]:
                    print(f"WARNING {folder}: {message}")
                if result["errors"]:
                    failed = True
                else:
                    print(f"OK {folder}: risk={result['riskLevel']} sha256={result['bundleSha256']}")
            except Exception as exc:
                print(f"ERROR {folder}: {exc}")
                failed = True
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
