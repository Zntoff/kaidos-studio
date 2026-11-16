# Security

## Credentials and local API

Kairos uses each person's own provider credentials. The UI receives readiness and masked hints, never a full API key. Provider requests run in the backend. JSON responses redact configured secrets and common key formats. Provider errors no longer include arbitrary response bodies. Credential-bearing provider connections require HTTPS, except for explicitly local loopback servers; automatic provider redirects are not followed.

- Windows encrypts keys with DPAPI for the current user in `%LOCALAPPDATA%/ClipperStudio/settings.ai.json`. Software running as that user or an administrator remains within the operating system's trust boundary.
- Docker reads user-provided environment variables or `data/settings.ai.json`. Saved keys have owner-only permissions (`0600`) where supported. This file is not encrypted: protect the data folder, its backups and the Docker host. None of these files are included in release packages or images.
- Desktop binds only to `127.0.0.1` on a random port. Compose publishes only `127.0.0.1:8000` by default.
- API access requires an HttpOnly, SameSite Strict session cookie. Changes also require a CSRF header. Host and Origin checks reject external pages and DNS rebinding. Cookie names include the port to isolate simultaneous instances.
- Private HTML/JSON responses use `no-store`. CSP, anti-framing and `nosniff` headers reduce additional attack surfaces. Executable and SVG reference uploads are rejected.
- `/healthz` exposes only service availability. Private API routes are not anonymous health probes.

This session protects a local, single-user application; it is not a multi-user login system. Do not expose the container publicly or on a shared network without HTTPS and authentication at a reverse proxy. `CLIPPER_TRUSTED_HOSTS` permits explicit proxy hostnames; it does not authenticate users. Do not enable open CORS.

## Deletion and recovery

Deletion requires confirmation. A project deletion removes its videos, jobs, shorts and resources; a video deletion removes its jobs and shorts. General remains available. Active project work blocks deletion; mutations are serialized to avoid races with imports.

Only managed files are moved. External originals and files referenced by surviving projects remain intact. Removed files and record manifests are retained in `data/trash` or `%LOCALAPPDATA%/ClipperStudio/trash`. Windows exports on another drive use `.kairos-trash` inside the output folder. Recovery is manual using the manifest; there is no automatic purge. Recovery folders contain private user content and must not be distributed.

## Windows signing and distribution

`desktop/publish.ps1` builds a self-contained folder without a compressed, self-extracting executable. No administrator privileges or antivirus exclusions are requested. Packages include `SHA256SUMS.txt` and `signing-report.json`; packaging rejects private configuration, user libraries and signing material.

`desktop/sign.ps1` supports code-signing certificates in the Windows certificate store and Microsoft Artifact Signing. It uses SHA-256, RFC 3161 timestamps and Authenticode verification for the app's own EXE and DLL. `-RequireSignature` blocks publication without a configured identity or a valid, timestamped signature. No self-signed fallback is created. Unsigned local builds report `publicReleaseReady: false`. Third-party tools are not re-signed as if they were our own. Checksums establish integrity, not publisher identity.

A valid signature identifies the publisher and helps build reputation; it does not guarantee acceptance by every antivirus or SmartScreen, especially for a new release. Do not disable those protections or ask users to do so. Investigate any detection and use the vendor's official false-positive process; do not modify code to evade detection.

See [Microsoft signing options](https://learn.microsoft.com/windows/apps/package-and-deploy/code-signing-options), [SmartScreen reputation](https://learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation), and [Artifact Signing integration](https://learn.microsoft.com/azure/trusted-signing/how-to-signing-integrations).

## Reporting vulnerabilities

Use GitHub Security > Report a vulnerability when enabled. Do not post keys, private data folders or sensitive reproductions in a public issue. Revoke an exposed key with its provider; deleting it from the repository does not remove it from history.
