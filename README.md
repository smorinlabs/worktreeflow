# worktreeflow

Git workflow manager for feature branches using worktrees.

## Quick Start

### Using Dev Container (Recommended)

The fastest way to get started is using the dev container, which provides a pre-configured environment with Python, uv, and git.

#### Option 1: VS Code Dev Containers

1. **Prerequisites**:
   - Install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
   - Install [VS Code](https://code.visualstudio.com/)
   - Install the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

2. **Open in Container**:
   ```bash
   # Clone the repository
   git clone https://github.com/smorinlabs/worktreeflow.git
   cd worktreeflow

   # Open in VS Code
   code .
   ```

3. **Reopen in Container**:
   - VS Code will detect the `.devcontainer` configuration
   - Click "Reopen in Container" when prompted (or use Command Palette: `Dev Containers: Reopen in Container`)
   - Wait ~30 seconds for the container to build and start

4. **Start Using**:
   ```bash
   ./wtf --help
   ./wtf doctor
   ```

#### Option 2: GitHub Codespaces

1. Go to the [repository on GitHub](https://github.com/smorinlabs/worktreeflow)
2. Click the **Code** button → **Codespaces** tab → **Create codespace on main**
3. Your browser opens with a fully configured VS Code environment
4. Run `./wtf --help` to get started

**Benefits**: Zero local setup, works from any device with a browser.

### Local Installation (Without Dev Container)

If you prefer to run locally without Docker:

1. **Prerequisites**:
   - Python 3.9+
   - [uv](https://docs.astral.sh/uv/) package manager

2. **Install uv**:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. **Run the tool**:
   ```bash
   ./wtf --help
   ```

   The script automatically installs its dependencies via uv on first run.

## Usage

```bash
# Check your environment
./wtf doctor

# Sync your fork's main branch
./wtf sync-main

# Create a new feature worktree
./wtf wt-new my-feature

# Publish your branch
./wtf wt-publish my-feature

# Create a pull request
./wtf wt-pr my-feature

# Update worktree with upstream changes
./wtf wt-update my-feature

# Clean up worktree after merge
./wtf wt-clean my-feature --confirm
```

For detailed documentation, run:
```bash
./wtf --help
./wtf tutorial
./wtf quickstart
```

## Installation from PyPI

Once published, you can install `worktreeflow` via pip or pipx:

```bash
# Using pipx (recommended for CLI tools)
pipx install worktreeflow

# Or using pip
pip install worktreeflow

# Or using uv
uv tool install worktreeflow
```

Then use either the `wtf` or `worktreeflow` command:
```bash
# Short form
wtf --help
wtf doctor

# Full name (same functionality)
worktreeflow --help
worktreeflow doctor
```

## Development

### Setting Up Development Environment

The dev container includes:
- Python 3.12
- uv package manager
- git (latest)
- VS Code extensions: Ruff, Python, Pylance
- Auto-formatting on save

All dependencies are automatically installed via the `wtf` script's inline metadata.

### Building and Publishing

1. **Build the package**:
   ```bash
   uv build
   ```
   This creates `dist/worktreeflow-0.1.0-py3-none-any.whl` and `dist/worktreeflow-0.1.0.tar.gz`

2. **Test locally**:
   ```bash
   uv pip install dist/worktreeflow-0.1.0-py3-none-any.whl
   wtf --help
   ```

3. **Publish to PyPI**:
   ```bash
   # First time: Get API token from https://pypi.org/manage/account/token/
   # Then set it in your environment or use --token flag

   uv publish
   ```

### Dual Functionality

This package supports **two usage patterns**:

1. **Standalone script** (via uv shebang):
   ```bash
   ./wtf --help
   ```
   Dependencies are automatically installed from inline metadata.

2. **Installed package** (via PyPI):
   ```bash
   pip install worktreeflow
   wtf --help
   # or
   worktreeflow --help
   ```
   Dependencies are installed from `pyproject.toml`.
   Both `wtf` and `worktreeflow` commands are available after installation.
