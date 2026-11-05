# Security policy

## Supported versions

Security fixes go into the latest release. Upgrade to it to get them.

## Reporting a vulnerability

Please report privately through GitHub: [open a security advisory](https://github.com/ashhadahsan/fastapi2postman/security/advisories/new). Don't open a public issue.

Include the version, a minimal example and what an attacker could do with it. The fix ships as a patch release, with credit in the advisory unless you'd rather not be named.

## What to look at

- **It runs your code.** The command imports the app you point it at, so module-level code in that app runs. Only point it at code you trust.
- **Secrets in the collection.** Generated collections are meant to be shared, so credentials must only ever appear as blank variables. Anything you declare in the app's schema, such as `examples=` and defaults, is copied into the file as written, so keep real values out of those.
- **The release pipeline.** Releases are built in GitHub Actions and published to PyPI with Trusted Publishing and attestations.
