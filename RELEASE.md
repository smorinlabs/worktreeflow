# Release Process

## Versioning

worktreeflow follows [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).

The **single source of truth** for the version is `pyproject.toml`. The Python package reads the version at runtime via `importlib.metadata`, so there is only one place to update.

## Bump Version

Use the Makefile targets to bump the version:

```bash
# Show current version
make version

# Bump patch (0.3.0 → 0.3.1) — bug fixes
make bump-patch

# Bump minor (0.3.0 → 0.4.0) — new features, backwards compatible
make bump-minor

# Bump major (0.3.0 → 1.0.0) — breaking changes
make bump-major
```

After bumping, run `uv sync` to refresh the editable install so `wtf version` reflects the new version.

## Full Release

The `make release` target automates: bump → sync → commit → tag.

```bash
# Patch release (default)
make release

# Minor release
make release BUMP=minor

# Major release
make release BUMP=major
```

This will:
1. Bump the version in `pyproject.toml`
2. Run `uv sync` to update the local install
3. Commit the version change
4. Create a git tag (e.g., `v0.4.0`)

It does **not** push automatically. Review the commit and tag, then:

```bash
git push && git push --tags
```

## Publishing to PyPI

### Automated (Recommended)

Publishing is handled by GitHub Actions. The workflow (`.github/workflows/publish.yml`) triggers when a **GitHub Release** is published:

1. Push the version bump and tag (see above)
2. Go to [GitHub Releases](https://github.com/smorinlabs/worktreeflow/releases)
3. Click **Draft a new release**
4. Select the tag you just pushed (e.g., `v0.4.0`)
5. Add release notes
6. Click **Publish release**

The CI will automatically:
- Run the test suite
- Build the package with `uv build`
- Publish to PyPI via OIDC (trusted publisher)

### Manual

If you need to publish manually:

```bash
uv build
uv publish  # requires PyPI API token
```

## Pre-Release Checklist

- [ ] All tests pass (`make test`)
- [ ] Linting passes (`make lint`)
- [ ] Type checking passes (`make typecheck`)
- [ ] Version bumped (`make bump-patch` / `bump-minor` / `bump-major`)
- [ ] `uv sync` run after bump
- [ ] `wtf version` shows correct version
- [ ] Changes committed and tagged (`make release`)
- [ ] Pushed to remote (`git push && git push --tags`)
- [ ] GitHub Release created
