# Release process

1. Update `VERSION` and `CHANGELOG.md`.
2. Run the Windows installer on a clean Windows 10/11 user account.
3. Verify `doctor.ps1`, `verify-install.ps1`, MCP registration, dedicated Chrome sign-in, and the minimal
   `ask_pro_architect` marker call.
4. Confirm the repository has no Chrome profile, log, token, cookie, venv, or local
   configuration files staged.
5. Create and push an annotated Git tag such as `v0.2.0`.
6. The `Release Windows package` GitHub workflow builds
   `pro_bridge_codex-windows-x64-v<version>.zip`, generates `SHA256SUMS.txt`, and creates
   the GitHub Release with generated notes.
7. Add known issues, upgrade notes, and rollback instructions before marking the Release
   stable.

Before the first stable release, test the installer on a device that was not used for
development. Windows is the only supported installation target in this release line.
