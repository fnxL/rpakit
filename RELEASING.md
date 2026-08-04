# Releasing rpakit

This project uses a **manual, tag-triggered** release process:
you decide the version and when to ship it; CI does the build, changelog,
GitHub Release, and PyPI publish.

- [CI.yml](.github/workflows/ci.yml) — runs on every push/PR to `main`: lint
  (`ruff`), type-check (`ty`), tests (`pytest` on Python 3.11–3.14), and a
  packaging smoke build.
- [release.yml](.github/workflows/release.yml) — runs when a tag matching
  `v*.*.*` is pushed: re-verifies the version, builds, generates the
  changelog, creates the GitHub Release, and publishes to PyPI.

Commit messages **must** follow [Conventional Commits](https://www.conventionalcommits.org/)
(`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, `chore:`, ...) —
this repo already does. The changelog generator ([git-cliff](https://git-cliff.org),
config in [cliff.toml](cliff.toml)) groups entries by commit type, so
inconsistent prefixes show up as messy/missing changelog sections.

---

## One-time setup

Do these once, before the first tagged release.

### 1. Create the `pypi` GitHub Environment

The publish job deploys through a GitHub Environment named `pypi` so you can
(optionally) require manual approval before anything goes to PyPI.

1. Repo → **Settings → Environments → New environment** → name it `pypi`.
2. (Optional but recommended) under **Deployment protection rules**, check
   **Required reviewers** and add yourself — this makes every publish wait
   for you to click "approve" in the Actions run.

### 2. Register a PyPI Trusted Publisher

Trusted Publishing (OIDC) lets GitHub Actions publish to PyPI **without any
API token/secret** — PyPI verifies the workflow's identity directly.

Since `rpakit` isn't on PyPI yet, register a *pending* publisher:

1. Go to <https://pypi.org/manage/account/publishing/> (log in first).
2. Under "Add a new pending publisher", fill in:
   - **PyPI Project Name**: `rpakit`
   - **Owner**: `fnxL`
   - **Repository name**: `rpakit`
   - **Workflow name**: `release.yml`
   - **Environment name**: `pypi`
3. Save. The first successful run of `release.yml` will create the project
   on PyPI and bind the publisher permanently — no further PyPI-side config
   needed for future releases.

*(If `rpakit` already existed on PyPI, you'd do this under that project's
"Publishing" settings instead of "pending publishers".)*

### 3. Allow the release workflow to push to `main`

The `changelog` job commits the regenerated `CHANGELOG.md` back to `main`.
If branch protection is enabled on `main`:

- Repo → **Settings → Branches → main → Edit** → under "Restrict who can
  push", make sure `github-actions[bot]` is allowed, **or** enable
  "Allow specified actors to bypass required pull requests" for it.
- If you'd rather not grant that, you can skip this: remove the
  "Commit CHANGELOG.md to main" step from `release.yml` and just rely on the
  per-release notes attached to each GitHub Release instead.

Repo → **Settings → Actions → General → Workflow permissions** should also
have **"Read and write permissions"** selected (needed for the release
commit and for creating the GitHub Release).

---

## Cutting a release

1. Make sure `main` is green (CI passing) and has everything you want to ship.
2. Decide the next version per [SemVer](https://semver.org/):
   `MAJOR.MINOR.PATCH` — bump `MAJOR` for breaking changes, `MINOR` for new
   backwards-compatible features, `PATCH` for fixes only.
3. Bump the version in `pyproject.toml`:
   ```toml
   [project]
   version = "0.2.0"
   ```
4. Commit it:
   ```bash
   git add pyproject.toml
   git commit -m "chore(release): 0.2.0"
   git push origin main
   ```
5. Tag and push — **the tag is what triggers the release**:
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```
6. Watch the **Release** workflow in the Actions tab. It will:
   - fail fast if the tag (`0.2.0`) doesn't match `pyproject.toml`'s version;
   - run the full test suite again;
   - build the sdist + wheel and smoke-test the wheel;
   - regenerate `release-notes.md` (this version only) and `CHANGELOG.md`
     (full history) via git-cliff, and push the updated `CHANGELOG.md` to
     `main`;
   - create a GitHub Release at the tag with the build artifacts attached
     and the generated notes as its body;
   - publish the wheel + sdist to PyPI (waiting for your approval first, if
     you enabled required reviewers on the `pypi` environment).
7. Confirm: <https://pypi.org/project/rpakit/> shows the new version, and
   the repo's **Releases** page has the new entry.

To fix a botched release, delete the tag and GitHub Release, fix the issue,
and re-tag — do **not** try to reuse or force-push a version number that was
ever published to PyPI (PyPI permanently blocks re-uploading a deleted
version).

---

## Pre-releases (optional)

Push a tag like `v0.2.0rc1` or `v0.2.0b1` — the workflow's version check
compares the tag verbatim against `pyproject.toml`, so bump to a matching
pre-release version (`version = "0.2.0rc1"`) before tagging. PyPI will list
it as a pre-release automatically based on the version string.
