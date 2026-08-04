# Releasing rpakit

This project uses a **manual, tag-triggered** release process:

- [CI.yml](.github/workflows/ci.yml) — runs on every push/PR to `main`: lint
  (`ruff`), type-check (`ty`), tests (`pytest` on Python 3.11–3.14), and a
  packaging smoke build.
- [release.yml](.github/workflows/release.yml) — runs when a tag matching
  `v*.*.*` is pushed: re-verifies the version, builds, generates the
  release-notes, creates the GitHub Release, and publishes to PyPI.

Commit messages **must** follow [Conventional Commits](https://www.conventionalcommits.org/)
(`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, `chore:`, ...)

---

## Release
1. Bump version using uv
2. Commit
3. Push
4. Git tag and push
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```
