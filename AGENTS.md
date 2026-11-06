# Repository Guidelines

## Project Structure & Module Organization

This repository is a Python 3.12 user service that mirrors unread Microsoft
Teams Activity items as KDE notifications. Keep application code in
`src/notification_service/`:

- `core/` contains provider contracts, scheduling, event/state handling, and
  deduplication.
- `providers/teams_activity/` owns Playwright and Teams-specific parsing.
- `delivery/` contains the generic desktop-notification adapter.
- `tests/` mirrors `src/`; keep sanitized Teams DOM fixtures in
  `tests/fixtures/`.
- `docs/` holds design, security, and operating notes. Do not commit browser
  profiles, cookies, tokens, or real Teams content.

## Build, Test, and Development Commands

Use `uv` for the locked Python environment:

```bash
uv sync --all-groups        # install locked dependencies
uv run playwright install chromium
uv run pytest               # unit and integration tests
uv run ruff check .         # lint
uv run mypy src             # static types
uv run teams-notify status  # validate local configuration/session
```

Run `uv run teams-notify login` only in a graphical user session. It opens the
dedicated browser profile for manual authentication; never automate credentials.

## Coding Style & Naming Conventions

Use four spaces, type annotations for public functions, `snake_case` modules
and functions, `PascalCase` classes, and immutable event data where practical.
Keep provider-specific code out of `core/`. Prefer small async functions with
explicit failures over hidden retries. Format and lint with Ruff; do not add a
dependency for a small standard-library solution.

## Testing Guidelines

Write `pytest` tests named `test_<behavior>`. Cover new parsing, state, and
deduplication branches with fixtures or mocks; browser tests must use local,
sanitized HTML rather than live Teams. Verify that delivery is recorded only
after a successful D-Bus call. Run the full commands above before a PR.

## Commits, Pull Requests, and Security

Git is initialized but has no commits yet. Use concise imperative Conventional
Commit titles, for example `feat: add Teams activity parser`. Keep PRs focused,
explain the user-visible change and tests run, and link the relevant issue when
one exists. All agent changes require Codex review before merge; do not merge or
broaden scope without that review.

Treat the Playwright profile as a secret. Keep state directories `0700`, avoid
logging notification bodies, page HTML, cookies, or token-bearing URLs, and do
not weaken systemd sandboxing without documenting why it is required.
