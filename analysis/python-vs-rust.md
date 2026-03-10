# Python vs Rust: Should worktreeflow Be Ported?

**Date:** 2026-03-10
**Application:** worktreeflow — a Git workflow manager for feature branches using worktrees (~2,064 LOC, single-file CLI tool)

---

## 1. Executive Summary

**Recommendation: Stay with Python.**

worktreeflow is an I/O-bound CLI orchestration tool that shells out to `git` and `gh` for nearly all of its work. The application's performance ceiling is determined by Git and network operations, not by the language runtime. A Rust port would add significant development and maintenance cost for negligible user-visible benefit, while sacrificing the rapid iteration speed and ecosystem fit that Python provides for this type of tool.

---

## 2. What worktreeflow Actually Does

Before analyzing languages, it's critical to understand what the code *does*:

- **Orchestrates shell commands** — Most operations call `git` or `gh` via subprocess or GitPython.
- **Validates user input** — Branch names, slugs, repository state.
- **Manages file paths** — Constructing and checking worktree directories.
- **Renders terminal output** — Rich tables, panels, colored text.
- **Parses text output** — Git porcelain output, remote URLs.

The application does **no** CPU-intensive computation, **no** concurrent processing, **no** large data structure manipulation, and **no** memory-intensive work. It is a thin coordination layer over Git.

---

## 3. Potential Benefits of Rust

### 3.1 Startup Time
- **Python**: ~100-300ms cold start (importing click, rich, gitpython).
- **Rust**: ~1-5ms cold start (native binary, no interpreter).
- **Verdict**: Noticeable but minor. Each `wtf` command runs infrequently (a few times per hour at most). The 200ms difference is imperceptible in a developer workflow where the subsequent `git fetch` takes 1-5 seconds.

### 3.2 Single Binary Distribution
- Rust compiles to a single static binary with zero runtime dependencies.
- Python requires a Python interpreter + dependencies (though `uv` mitigates this with its inline script mode and `pipx` handles it for package installs).
- **Verdict**: Genuine advantage for distribution, but `uv` and `pipx` have largely solved this for Python CLIs.

### 3.3 Memory Safety and Security
- Rust's ownership model eliminates use-after-free, buffer overflows, and data races.
- The current codebase has shell injection vulnerabilities (bugs B02, B05) that stem from string interpolation into shell commands — a class of bug that **Rust does not prevent** since it's a logic issue, not a memory issue.
- **Verdict**: Minimal benefit. This application doesn't have memory safety concerns — it's a short-lived CLI, not a long-running server handling untrusted input.

### 3.4 Type Safety
- Rust has stronger compile-time guarantees (exhaustive match, no null, Result types).
- Python with type hints + mypy gets ~80% of the way there.
- **Verdict**: Moderate benefit for correctness, but the existing Python code already uses type hints extensively.

### 3.5 No Runtime Dependency
- No need for Python to be installed on the target machine.
- **Verdict**: Minor benefit. The target audience (developers using Git worktrees and GitHub forks) already has Python installed.

---

## 4. Downsides and Risks of Porting to Rust

### 4.1 Development Effort — HIGH RISK
- **Estimated effort**: 2-4 weeks for an experienced Rust developer; 6-12 weeks for someone learning Rust.
- The current ~2,064 lines of Python would expand to roughly **4,000-6,000 lines of Rust** due to:
  - Explicit error handling (`Result<T, E>` everywhere)
  - String handling verbosity (`&str` vs `String` vs `OsStr` vs `Path`)
  - Boilerplate for CLI argument parsing
  - No equivalent to GitPython's high-level API
- This is a complete rewrite, not an incremental port.

### 4.2 Git Library Ecosystem — HIGH RISK
- **Python (GitPython)**: Mature, well-documented, high-level API covering all operations worktreeflow uses.
- **Rust (git2-rs/libgit2)**: Lower-level, doesn't cover all Git operations (worktrees have limited support), meaning you'd still need to shell out to `git` for key operations.
- The Rust port would likely end up calling `std::process::Command` for the same operations the Python version calls `subprocess.run()` for — negating the "pure Rust" advantage.

### 4.3 CLI Framework Maturity — MEDIUM RISK
- **Python (Click)**: Battle-tested, rich feature set (groups, chaining, help generation, shell completion).
- **Rust (clap)**: Excellent and comparable, but migrating 19 commands with their options, help text, and validation is tedious work.

### 4.4 Rich Terminal Output — MEDIUM RISK
- **Python (Rich)**: Unmatched library for terminal UI — tables, panels, markdown rendering, syntax highlighting, progress bars.
- **Rust alternatives**: `comfy-table`, `tui-rs`, `console` exist but are more fragmented and less polished. Reproducing the current Rich output would require combining multiple crates and more code.

### 4.5 Maintenance Burden — HIGH RISK
- The tool is in active development (v0.2.0, 12 known bugs).
- Rust's compilation times slow down the edit-test cycle.
- The target contributor audience (developers who use Git worktrees) is far more likely to know Python than Rust.
- Bug fixes and feature additions are 2-5x faster to implement in Python for this type of tool.

### 4.6 Cross-Platform Building — MEDIUM RISK
- Python runs everywhere Python exists (which is everywhere developers work).
- Rust requires cross-compilation setup for each target (x86_64-linux, aarch64-linux, x86_64-darwin, aarch64-darwin, x86_64-windows). CI matrix complexity increases significantly.

### 4.7 Loss of Script Mode — LOW-MEDIUM RISK
- The current `wtf.py` can be run directly as a script via `uv` with inline dependency metadata — a zero-install experience.
- A Rust binary must be compiled and distributed. There's no "just download and run the source" path.

---

## 5. Comparative Analysis

| Factor | Python | Rust | Winner |
|---|---|---|---|
| **Performance** | Fast enough (I/O bound) | Faster startup, same I/O | Tie (bottleneck is Git, not language) |
| **Distribution** | pipx/uv handles it well | Single binary | Slight Rust edge |
| **Development speed** | Fast iteration | Slower, more verbose | **Python** |
| **Git library support** | GitPython (excellent) | git2 (limited worktree support) | **Python** |
| **CLI frameworks** | Click (excellent) | clap (excellent) | Tie |
| **Terminal UI** | Rich (unmatched) | Fragmented ecosystem | **Python** |
| **Type safety** | Good (with mypy) | Excellent (compiler-enforced) | Slight Rust edge |
| **Contributor accessibility** | High (Python is ubiquitous) | Lower (Rust is niche) | **Python** |
| **Maintenance cost** | Low | Higher | **Python** |
| **Security (memory)** | N/A for this app | N/A for this app | Tie |
| **Security (injection)** | Must be careful | Must still be careful | Tie |
| **Cross-platform** | Automatic | Requires cross-compilation | **Python** |

**Score: Python 5, Rust 2, Tie 4**

---

## 6. When a Rust Port *Would* Make Sense

A Rust rewrite would be justified if any of these became true:

1. **The tool needed to process large amounts of Git data** (e.g., analyzing thousands of commits, diffing large repos) — currently it doesn't.
2. **The tool became a long-running daemon** (e.g., watching for file changes, auto-syncing) — currently it's a one-shot CLI.
3. **Distribution to non-developers** became a goal (users who don't have Python) — currently the audience is Git power users.
4. **Startup latency became critical** (e.g., the tool was called in a tight loop by another tool) — currently it's human-invoked.
5. **The project stabilized and rarely changed** — currently it's v0.2.0 with 12 known bugs and active development.

---

## 7. Better Alternatives to a Full Rust Port

If specific Rust benefits are desired, consider these targeted approaches:

### 7.1 PyO3/Maturin Hybrid (Best of Both Worlds)
Write performance-critical components in Rust and call them from Python via PyO3. This preserves the Python CLI while getting Rust speed where it matters. *However, there are no performance-critical components in this app, so this is a solution looking for a problem.*

### 7.2 PyInstaller/Nuitka (Single Binary Without Rust)
If single-binary distribution is the goal, compile the Python application with PyInstaller or Nuitka. This gives a single executable without rewriting anything.

### 7.3 Invest in the Python Codebase Instead
The best ROI for this project is:
- Fix the 3 critical bugs (shell injection, off-by-one, IndexError)
- Add a test suite
- Run mypy in strict mode for stronger type safety
- Replace `shell=True` subprocess calls with argument lists (fixes the injection bugs *and* improves security more than any language change would)

---

## 8. Final Verdict

**Stay with Python. Invest in quality, not a rewrite.**

The case for Rust is weak because:
- The application is **I/O-bound** — Git and network operations dominate runtime
- The Python ecosystem is **superior** for this use case (GitPython, Click, Rich)
- The project is **early-stage** and actively evolving — rewrites during active development are high-risk
- The target audience **already has Python** installed
- The security issues are **logic bugs**, not memory safety bugs — Rust won't fix them
- Development velocity matters more than runtime velocity for a developer tool

The ~200ms startup time improvement and single-binary distribution do not justify the 2-4 week rewrite effort, 2-3x code expansion, reduced contributor pool, and ongoing higher maintenance cost.

**The right move is to make the Python version excellent** — fix the known bugs, add tests, and tighten the type checking. That investment will deliver far more value than a language port.
