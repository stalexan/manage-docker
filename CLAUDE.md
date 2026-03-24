# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python module (no build system, no tests) providing a CLI framework for managing Docker Compose
containers with a plugin system for project-specific commands.

Installed once to a shared location (e.g. `~/.local/share/manage-docker`) and discovered by host
projects via the `MANAGE_DOCKER_HOME` environment variable. Imported via `from manage import main`.

## Architecture

Single-module design — all logic lives in `core.py`, re-exported through `__init__.py`.

**Key flow:** `main(script_path)` → `load_plugins()` → `build_parser()` → `args.func(ctx)`

- `ProjectConfig` — dataclass for project-specific settings (compose files, environment pattern)
- `CommandContext` — passed to all command handlers; wraps docker compose invocation, service status
  checks
- `_command_registry` / `_subcommand_registry` — global dicts populated by `@register_command` and
  `@register_subcommand` decorators when plugin files are imported
- `load_plugins()` — dynamically imports `manage_plugins.py` from the host project's script
  directory using `importlib`; decorator side-effects populate the registries
- `build_parser()` — builds argparse tree from built-in commands + registered plugin
  commands/subcommands

## Plugin System

Host projects provide `scripts/manage_plugins.py` containing:
1. A `config = ProjectConfig(...)` module-level variable
2. Functions decorated with `@register_command` or `@register_subcommand`

Arguments use argparse dict format: `{"args": ["-v", "--verbose"], "action": "store_true", "help": "..."}`.

## Conventions

- Python 3, no external dependencies (stdlib only: argparse, subprocess, importlib, dataclasses)
- Command handlers take `(ctx: CommandContext) -> None` and use `ctx.compose()` for docker operations
- Output uses `print_status`/`print_success`/`print_warning`/`print_error`/`fatal` helpers (ANSI colored)
- `run()` wraps `subprocess.run` with logging; `cmd_shell` uses `os.execvp` to replace the process
