# Official marketplace signing-key setup

Signing is intentionally fail-closed. The repository cannot publish a trusted catalogue until the private key exists as a GitHub Actions secret and the matching public key is pinned in the app.

## Generate an ECDSA P-256 key pair in a private Codespace

Run these commands in a private GitHub Codespace or another trusted terminal. Do not run them in a public Codespace or a third-party website.

    openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out marketplace-private.pem
    openssl pkey -in marketplace-private.pem -pubout -out marketplace-public.pem
    openssl pkey -pubin -in marketplace-public.pem -outform DER | base64 -w0

The last command prints the X.509 SubjectPublicKeyInfo value. Copy that public value into MarketplaceTrust.OFFICIAL_PUBLIC_KEY_X509_BASE64 in the OpenTasker app source, then commit it to Experimental.

## Store the private key as a GitHub secret

Use GitHub CLI while authenticated as a repository administrator:

    base64 -w0 marketplace-private.pem | gh secret set MARKETPLACE_SIGNING_PRIVATE_KEY_B64 --repo PatentPuddle9/OpenTasker_Makrketplace

The workflow expects the secret to contain base64-encoded PEM text. It decodes the secret into a temporary file, signs catalog/v1/index.json, then deletes the temporary key file.

After the public key is pinned in the app and the secret is configured, run the "Publish signed marketplace catalogue" workflow manually. Verify the app accepts the catalogue and rejects a modified catalogue and modified bundle.

## Rotation

Treat the private key as an offline signing credential. For rotation, publish a reviewed app update with the new public key and coordinate the transition before replacing the marketplace secret. Never trust a public key downloaded from the same untrusted catalogue it is meant to verify.
