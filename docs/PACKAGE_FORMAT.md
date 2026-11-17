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

## Deleting and reusing a package ID

When a publisher's deletion request is processed, the Marketplace removes every version directory for that package ID from the repository. The deletion record remains in `moderation/decisions.json` for audit history, but it does not reserve the ID. Any creator can then submit a new package using that ID, starting again at **1.0.0**. The new listing has a fresh publisher and version history; the previous publisher cannot update or delete the new package unless they are its publisher too.

Previously imported automations remain installed on users' devices. Removing the Marketplace source files only prevents new downloads of the withdrawn versions.


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
- `icon`: A built-in OpenTasker icon key, such as `"bolt"`, `"house-01"`, or `"volume-max"`. Custom images are not accepted as listing-decoration icons; distribute reusable PNGs as a separate `Custom Widget Icons` package.
- `iconColor` and `backgroundColor`: Six-digit hex colors, with or without a leading `#`.
- `gradient`: Whether the listing icon background uses a gradient.
- `shape`: One of `squircle`, `rounded_square`, `circle`, `square`, or `teardrop`.
- `changelog`: Notes describing what changed in this version (up to 2000 characters).
- `documentationUrl`: Optional HTTPS link to setup instructions or documentation.
- `faqs`: Up to 10 entries shaped as `{"question":"...","answer":"..."}`; questions are limited to 160 characters and answers to 1,200.
- `dependencies`: Up to 10 package requirements shaped as `{"id":"package-id","minimumVersion":"1.2.3","optional":false}`. IDs must be valid and cannot refer to the package itself.
- `screenshots`: Optional list of up to 4 additional PNGs stored at `screenshots/01.png` through `screenshots/99.png`. Each file must be a valid PNG no larger than 2 MB and no dimension larger than 2048 × 2048. The signed catalogue records the SHA-256 hash for each screenshot; OpenTasker verifies it before display.


These are presentation and discovery fields only. They do not change the bundle's permissions, risk classification, or import behavior. The app always verifies the signed catalogue and bundle hash, and imported profiles still start disabled.

## Optional bundled images and audio

Action, Shortcut Widget, and Widget Display creators may include up to **12 optional media files** with each package version. Images selected in the publisher app may be PNG, JPG, or WebP; they are re-encoded as metadata-clean PNGs, limited to 2048 × 2048 pixels and 5 MB each. Audio may be MP3, OGG, WAV, or M4A, up to 10 MB each. Combined media may not exceed 40 MB. Media files are data only; executable files and arbitrary file paths are not accepted.

The publisher app assigns stable references such as `{{asset:asset-01}}` and includes a manifest entry for each file:

    {
      "assets": [
        {
          "key": "asset-01",
          "file": "assets/audio-01.mp3",
          "mediaType": "audio/mpeg",
          "sizeBytes": 123456,
          "sha256": "<64-character SHA-256 digest>"
        }
      ]
    }

Use the matching reference in an Action file/audio path field. Widget Display image elements may use the same reference in `imageUri`. The package must not contain the publisher's original `file://` or `content://` URI. During installation, OpenTasker verifies the signed catalogue path, SHA-256 digest, size, and media type, copies the file into the installer's chosen package-content folder (or app-private storage by default), and replaces the reference with that device's local URI. The creator can omit media entirely; packages without assets behave as before. A new immutable version must re-select any media files that should carry forward.

## Discovery, community reviews, and analytics

The signed catalogue includes the package publication timestamp, review summary and content, download totals, unique installer count, and downloads from the last seven days. The app uses those signed values for Recommended, Trending, Top Rated, Newest, and Most Downloaded sorting. A package's popularity metrics are not a substitute for its risk and review indicators.

Signed-in users can submit one written review per package and update it later. Reviews have a title (up to 100 characters) and body (up to 1,200 characters). A user cannot review their own package or mark their own review helpful. Reviews are public and linked to the reviewer's GitHub account; do not include private contact information or credentials.

Install analytics are opt-in: the app submits an install event only for a user signed in with GitHub. Events are deduplicated to one count per account/package/day. Guests can install packages without analytics. These are install events, not guaranteed unique device or human counts.

Collections are private to the device and stored locally. They do not sync to GitHub or become part of a package.

## Additional Marketplace package types

Marketplace packages may also use these categories. They are data-only formats; no scripts, native code, APKs, or executable plugins are accepted.

Both visual package types include a generated `preview.png` (PNG, at most 2 MB, up to 2048 × 2048). The OpenTasker publisher creates this image from the exact submitted payload, includes it in the package pull request, and the reviewer can open the image directly in GitHub before merging. The signed catalogue records the preview path and SHA-256 checksum, so the app can verify it before displaying it.

### Widget Displays

Use category `Widget Displays`. The `bundle.json` contains:

    {
      "schemaVersion": 1,
      "type": "widget_display",
      "config": {
        "canvasWidthDp": 320,
        "canvasHeightDp": 200,
        "states": []
      }
    }

The `config` object uses OpenTasker's Widget Display format, including its states, colors, and elements. The validator restricts the canvas to 110–1000 dp, up to 75 states, and up to 8 elements per state. Publisher-local Action references are removed before submission; recipients choose an installed Widget Display and connect their own Actions after applying the layout. Locally stored custom-icon references are not portable and are rejected. Widget Display packages that contain private `content://` image URIs are also rejected; use a layout without those private images.


### Custom Widget Icons

Use category `Custom Widget Icons`. The `bundle.json` contains:

    {
      "schemaVersion": 1,
      "type": "custom_widget_icon",
      "name": "My custom icon",
      "recolorable": false
    }

Include `assetFile: "icon.png"` in the manifest and place the square PNG at `icon.png` beside `manifest.json` and `bundle.json`. Icons may be up to 2048 × 2048 pixels and 15 MB. Installing the package adds the PNG to the recipient's Custom icon library. The package is still data-only; it cannot include executable content.

### Review and installation

Widget Displays and Custom Widget Icons use the same pull-request, validation, signed-catalogue, and merge process as Actions and Shortcut Widgets. Passing automated validation is not a manual security audit: the maintainer must inspect the pull request (including `preview.png`) before merging. The preview image is a visual aid; the app separately verifies the signed catalogue and each downloaded asset's checksum before use.


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
