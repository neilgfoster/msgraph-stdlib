<!--
PR title should be a Conventional Commit (e.g. `feat: ...`, `fix: ...`, `docs: ...`).
-->

## What and why

<!-- One paragraph: what this changes and why. -->

## Conventions

- [ ] Runtime stays **stdlib-only, zero-dependency, zero-backend** (`urllib`/`json`; ruff/pytest are
  dev tooling only).
- [ ] No secrets/tokens in the repo — they live outside it in an XDG path (`0600`).
- [ ] Any new/changed skill follows `docs/AGENT-FRIENDLY.md` (description + CLI I/O are the contract).
- [ ] Read-only safety model intact: `Mail.Read`-only read path, scope ratchet for writes,
  verify-then-install (read-only catch-set), file-to-folder (never delete).

## Verification

```sh
ruff check . && ruff format --check .
python3 -m pytest -q
```

- [ ] `ruff check .` and `ruff format --check .` pass.
- [ ] `python3 -m pytest -q` passes.
