# Installation

This guide installs Dolphin from source (the repository you are currently in).

## Requirements

- Python 3.10+ (3.11 recommended)
- Git
- One of:
  - `uv` (recommended, faster)
  - `pip`

## Option A: Use `uv` (recommended)

```bash
git clone https://github.com/kweaver-ai/dolphin.git
cd dolphin

# Create and sync `.venv/` with all dependency groups
make dev-setup

# Verify
make test
```

## Option B: Use `pip` + venv (no `uv`)

```bash
git clone https://github.com/kweaver-ai/dolphin.git
cd dolphin

# Create a clean venv under `env/`
python3.11 -m venv env/quick_start
source env/quick_start/bin/activate

# Install Dolphin (editable) + CLI dependencies
pip install -e ".[cli]"

# Verify
dolphin --version
dolphin --help
```

## Notes on offline environments

If your environment has no network access, you must prepare dependency wheels in advance
or use an existing pre-synced virtualenv (for example, one created by `make dev-setup`).

## Next

- [Quick Start](quickstart.md) - Learn basic usage and CLI commands
- [Basics](basics.md) - Understand core concepts
