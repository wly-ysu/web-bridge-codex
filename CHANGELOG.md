# Changelog

## 0.4.0

- Reuse one ChatGPT Web conversation per local project by default.
- Persist only a hashed project key and canonical conversation URL in an atomically written local registry.
- Add `conversation_mode` controls: `reuse_or_create`, `new`, and `one_shot`.
- Recover once only when a saved conversation is definitively unavailable; transient Web failures retain the mapping.
- Add deterministic tests for project isolation, safe persistence, and adapter reuse routing.

## 0.2.0-dev

- Add the Windows user-level installer, repair, diagnostics, and uninstaller.
- Add a bootstrap script for installing from the public GitHub repository.
- Register `web-bridge-codex` as a Codex MCP server without replacing existing MCP entries.
- Install a managed global Web-First workflow rule and a dedicated local Chrome profile.

## 0.1.0

- Delivered the MVP ChatGPT Web bridge for `ask_web_architect`.
