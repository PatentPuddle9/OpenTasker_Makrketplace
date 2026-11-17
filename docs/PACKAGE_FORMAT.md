# Marketplace package format

Every package version is a directory containing manifest.json and bundle.json:

    packages/<package-id>/<version>/manifest.json
    packages/<package-id>/<version>/bundle.json

## Version rules

A new package starts at **1.0.0**. Every update must use a new, immutable version directory. From the latest published version, the next version must advance exactly one part of MAJOR.MINOR.PATCH:

- Patch: 1.1.2 → 1.1.3
- Minor: 1.1.2 → 1.2.0
- Major: 1.1.2 → 2.0.0

Skipping values, changing more than one part at once, reusing a version, or moving backwards is rejected. Every update pull request requires a formal APPROVED review from another repository collaborator with write access. The publisher cannot approve their own update. High-risk updates also require trusted-moderator approval.

## Example manifest

    {
      "schemaVersion": 1,
      "id": "home-arrival-notice",
      "name": "Home arrival notice",
      "publisher": "YourGitHubLogin",
      "version": "1.0.0",
      "summary": "Sends a configurable message when a selected arrival trigger runs.",
      "category": "Automation",
      "minimumAppVersion": "1.0.0",
      "bundleFile": "bundle.json",
      "requiredInputs": [
        {
          "key": "recipient",
          "label": "Recipient phone number",
          "path": "/tasks/0/actions/0/args/phone",
          "required": true,
          "hint": "Enter the number that should receive the message."
        },
        {
          "key": "message",
          "label": "Message text",
          "path": "/tasks/0/actions/0/args/message",
          "required": true
        }
      ],
      "externalDestinations": []
    }

This is an illustrative structure. The JSON Pointer paths must match the actual fields in your exported bundle. The publisher value must match the GitHub login that opened the pull request.

## Listing appearance and discovery

The following optional fields control how the package appears in the OpenTasker Marketplace. Older manifests remain valid and receive the default bolt icon and purple app-icon styling.

- `description`: Full listing description (up to 4000 characters). Keep `summary` short and scannable.
- `tags`: Up to 10 plain-text search tags, such as `["home", "lighting", "notifications"]`.
- `icon`: A built-in OpenTasker icon key, such as `"bolt"`, `"house-01"`, or `"volume-max"`. Custom uploaded images are not accepted.
- `iconColor` and `backgroundColor`: Six-digit hex colors, with or without a leading `#`.
- `gradient`: Whether the listing icon background uses a gradient.
- `shape`: One of `squircle`, `rounded_square`, `circle`, `square`, or `teardrop`.
- `changelog`: Notes describing what changed in this version (up to 2000 characters).
- `documentationUrl`: Optional HTTPS link to setup instructions or documentation.

These are presentation and discovery fields only. They do not change the bundle's permissions, risk classification, or import behavior. The app always verifies the signed catalogue and bundle hash, and imported profiles still start disabled.


## Replace personal values in bundle.json

The bundle must contain the placeholder rather than a real value. For the example above, the two fields should contain:

    "phone": "{{input:recipient}}",
    "message": "{{input:message}}"

OpenTasker prompts the installing user for these values and substitutes them locally after verifying the signed bundle. The values entered on the device are not sent back to the marketplace.

Do not put a real phone number, contact ID, email address, home address, token, password, API key, or private webhook URL in bundle.json or manifest.json. The automated validator rejects detected personal data and credential-like values; it does not rewrite a submitted package on the contributor's behalf.

## Declare external services

For an HTTP request, webhook, or MQTT destination, include an item in externalDestinations:

    {
      "provider": "Home automation provider",
      "domain": "home.example.com",
      "hostingCountry": "Unknown",
      "privacyPolicyUrl": "https://home.example.com/privacy",
      "dataFields": ["event name", "device state"],
      "purpose": "Update the user's home automation",
      "privacyAssessment": "not-verified",
      "riskNotes": "Hosting location and third-party sharing have not been independently verified."
    }

The domain must match the external host used by the bundle. External destinations must use HTTPS unless they are private/local network addresses. Do not claim that a destination is verified without evidence. The app labels these values as publisher-declared and displays them to the installer.

Network/API, webhook, MQTT, SMS, contact access, device lock, security/settings changes, and unknown action IDs are high risk. High-risk packages require moderator approval and remain visibly high risk after approval.

## Important

- Published package versions are immutable. Create a new version directory for every update.
- Do not include scripts, shell commands, APKs, native libraries, or executable/plugin code.
- The catalogue's risk and review fields are generated by the repository. Do not add them to the manifest.
- Run the package through OpenTasker's normal import-review flow before submitting it.
