# Release process

1. Update `VERSION` and `CHANGELOG.md`.
2. Run the Windows installer on a clean Windows 10/11 user account.
3. Verify `doctor.ps1`, `verify-install.ps1`, MCP registration, dedicated Chrome sign-in, and the minimal
   `ask_pro_architect` marker call.
4. Confirm the repository has no Chrome profile, log, token, cookie, venv, or local
   configuration files staged.
5. Create an annotated Git tag such as `v0.2.0` and publish a GitHub Release.
6. Attach source or a packaged archive, a SHA-256 checksum, release notes, known issues,
   upgrade notes, and rollback instructions.

Before the first stable release, test the installer on a device that was not used for
development. Windows is the only supported installation target in this release line.
