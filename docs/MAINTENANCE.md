# Maintenance

Repository-operations policy, set up 2026-07-24. It applies to **both**
this repository and [tnj/aionatureremo](https://github.com/tnj/aionatureremo)
unless a section says otherwise.

## Dependency updates (Dependabot)

- **Version updates** run weekly (Monday 06:00 JST) for the `uv` and
  `github-actions` ecosystems, with a **7-day cooldown**: a release must be
  at least 7 days old before it is proposed. This trades a week of latency
  for protection against yanked/broken releases and supply-chain attacks
  that get caught within days of publication.
- **Security updates** are not subject to the cooldown and arrive
  immediately.
- Minor and patch updates are **grouped** (one PR per ecosystem per week).
  Majors always arrive as individual PRs. This repo keeps
  `homeassistant` + `pytest-homeassistant-custom-component` in their own
  group so a red HA bump cannot block unrelated tooling updates.
- This repo **ignores `aionatureremo`** in Dependabot: its version is pinned
  in `custom_components/nature_remo/manifest.json` and bumped by hand as
  part of the release process; Dependabot updating only `uv.lock` would
  desync the two.

## Auto-merge

- A workflow (`.github/workflows/dependabot-auto-merge.yml`) arms GitHub
  auto-merge (`gh pr merge --auto --squash`) on Dependabot PRs whose
  update-type is **semver-minor or semver-patch**. The PR then merges only
  when the `main` ruleset's required status checks pass.
- **Majors are never auto-merged** — they wait for human review.
- The safety of `--auto` depends entirely on the ruleset's required checks;
  if CI job names change, update the ruleset in the same PR.

## Branch protection (`main` ruleset)

- PRs required, 0 approvals, squash-only, required status checks
  (this repo: `lint` / `typecheck` / `test` / `hassfest`; library:
  `test (3.12)` / `test (3.13)` / `test (3.14)`), non-strict (PRs need not
  be up to date with main).
- **Repository admins bypass** the ruleset (mode: always) — the owner keeps
  pushing to main directly; Dependabot and external contributors go through
  green-CI PRs.
- Squash commits use the PR title as the message, so PR titles follow
  conventional-commit style.

## Dependency floors (this repo)

`pyproject.toml` floors `homeassistant>=2026.2` (the minimum declared in
`hacs.json`) and `pytest-homeassistant-custom-component>=0.13`. phcc pins
its matching HA version **exactly**, so the locked HA follows the newest
phcc release — and without the floors, resolvers (including Dependabot
security updates) dodge version conflicts by silently downgrading both to
ancient releases (observed 2026-07-24: the lock drifted to HA 2025.4.4 and
security PRs came out red). Keep the lock targeting the latest HA release;
`requires-python` follows HA's requirement.

## Security alert posture

Dependabot alerts on transitive dependencies that HA pins exactly (e.g.
pillow, pyjwt) cannot be fixed by a lockfile bump — such alerts stay open
without generating PRs and resolve when HA upgrades its pins. They affect
the dev/test environment only; the integration itself ships no bundled
dependencies.

## Releases

See `CLAUDE.md` (release order: implement → review → live verification →
release) and [CORE_SUBMISSION.md](CORE_SUBMISSION.md) for the core
submission plan. Library releases: bump `version` in `pyproject.toml`, tag
`vX.Y.Z`, push the tag — CI publishes to PyPI via trusted publishing.
