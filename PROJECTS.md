# Projects

**Legend:**
- `[x]` Completed
- `[-]` In Progress
- `[ ]` Not Started
- `[~]` Won't fix / Invalid / False positive

---

## [-] Project P16: Fix GitHub Actions Bugs + Makefile CI/Lefthook Recipes (v0.3.4)
**Goal**: Fix duplicate test execution bug in CI workflow, add Makefile recipes for CI dependency management, lefthook install, and manual lefthook runs

**Out of Scope**
- Raising the coverage threshold (currently 35%)
- Adding `permissions:` block to ci.yml (not a bug, just best practice)

### Tests & Tasks
- [x] [P16-T01] Fix duplicate pytest run for Python 3.12 in ci.yml
      Added `if: matrix.python-version != '3.12'` to plain test step so 3.12 only runs the coverage variant
- [x] [P16-T02] Add `-v --tb=short` flags to coverage test step for consistent verbose output
      Ensures 3.12 coverage run has same verbosity as other versions
- [x] [P16-T03] Add `make ci-deps` recipe — checks if uv/lefthook/actionlint are installed before installing, then runs `uv sync --group dev`
- [x] [P16-T04] Add `make lefthook-install` recipe — activates pre-commit hooks (errors if lefthook not found)
- [x] [P16-T05] Add `make lefthook-run` recipe — manually runs all pre-commit checks (errors if lefthook not found)
- [x] [P16-TS01] Validate ci.yml with actionlint — passed with no errors
- [x] [P16-TS02] Run full test suite — 159 tests passed
- [x] [P16-TS03] Verify `make help` shows all new targets
- [x] [P16-TS04] Verify `make ci-deps` detects already-installed tools
- [x] [P16-TS05] Verify `make lefthook-install` activates hooks
- [x] [P16-TS06] Verify `make lefthook-run` executes pre-commit checks
- [ ] [P16-TS07] Regression — push to branch and confirm CI passes on all 3 Python versions

### Deliverable
- `.github/workflows/ci.yml` — Python 3.12 no longer runs the test suite twice
- `Makefile` — 3 new recipes: `ci-deps`, `lefthook-install`, `lefthook-run`

### Automated Verification
- `actionlint .github/workflows/ci.yml` passes
- `make test` — 159 tests pass
- `make ci-deps` — detects installed tools, installs missing ones
- `make lefthook-install` — activates hooks
- `make lefthook-run` — runs pre-commit checks

### Manual Verification
- Push to a branch and confirm CI passes on all 3 Python versions (3.11, 3.12, 3.13)
- Confirm 3.12 job only shows one pytest execution (with coverage)
