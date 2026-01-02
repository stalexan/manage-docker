# manage-docker

A unified Python-based management system for Docker Compose projects. Provides common commands with project-specific customization via plugins.

## Installation

This module is designed to be used as a **git submodule** in your project:

```bash
# Add as a submodule to your project
git submodule add https://github.com/stalexan/manage-docker.git scripts/manage

# Or if cloning a project that uses this submodule:
git clone --recursive https://github.com/stalexan/your-project.git

# Or if you already cloned without --recursive:
git submodule update --init
```

## Quick Start

Each project has its own entry point that loads the shared core:

```bash
# From any project directory
./scripts/manage.py --help
./scripts/manage.py up
./scripts/manage.py logs -f
```

## Architecture

```
your-project/
├── scripts/
│   ├── manage/              # This repo as a submodule
│   │   ├── __init__.py
│   │   ├── core.py
│   │   └── README.md
│   ├── manage.py            # Entry point (imports from manage submodule)
│   └── manage_plugins.py    # Project-specific configuration and commands
└── docker-compose.yml
```

## Common Commands

| Command | Description |
|---------|-------------|
| `build [service...]` | Build images |
| `rebuild [service...]` | Full rebuild with `--pull --no-cache` |
| `up [service...]` | Start containers (detached) |
| `down [-v] [--remove-orphans]` | Stop containers |
| `restart [service...]` | Restart containers |
| `status` | Show container status |
| `logs [-f] [--tail N] [--since] [--timestamps] [service...]` | Show logs |
| `shell --service SERVICE` | Open shell in container |
| `clean [-y] [--volumes] [--all]` | Clean Docker resources |
| `stats [--no-stream]` | Container resource usage |

## Environment Switching

```bash
# Development (default)
./scripts/manage.py up

# Production
ENVIRONMENT=prod ./scripts/manage.py up

# Or use the --env flag
./scripts/manage.py --env prod up
```

## Creating a New Project

### 1. Add the Submodule

```bash
cd your-project
git submodule add https://github.com/stalexan/manage-docker.git scripts/manage
```

### 2. Create Entry Point

Create `scripts/manage.py`:

```python
#!/usr/bin/env python3
"""Manage Docker containers for my-project."""

import sys
from pathlib import Path

# Add manage submodule to path
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

from manage import main

if __name__ == "__main__":
    sys.exit(main(Path(__file__).resolve()))
```

Make it executable:
```bash
chmod +x scripts/manage.py
```

### 3. Create Plugin Configuration

Create `scripts/manage_plugins.py`:

```python
#!/usr/bin/env python3
"""Plugin commands for my-project."""

from manage import ProjectConfig

config = ProjectConfig(
    name="my-project",
    compose_files=["docker-compose.yml"],
    env_compose_pattern="docker-compose.{env}.yml",  # Optional
    default_env="dev",
)
```

### 4. Add Custom Commands (Optional)

```python
from manage import (
    ProjectConfig,
    CommandContext,
    register_command,
    register_subcommand,
    print_status,
    print_success,
    print_warning,
    print_error,
    fatal,
    confirm,
    run,
)

config = ProjectConfig(
    name="my-project",
    compose_files=["docker-compose.yml"],
)

@register_command(
    "my-command",
    help="Do something custom",
    arguments=[
        {"args": ["-v", "--verbose"], "action": "store_true", "help": "Verbose output"},
        {"args": ["name"], "help": "Name argument"},
    ]
)
def cmd_my_command(ctx: CommandContext) -> None:
    """Custom command implementation."""
    print_status(f"Running with name: {ctx.args.name}")
    if ctx.args.verbose:
        print_status("Verbose mode enabled")
    
    # Run docker compose commands
    ctx.compose("ps")
    
    # Run arbitrary commands
    run(["echo", "Hello"])
    
    print_success("Done!")
```

## Plugin API Reference

### ProjectConfig

```python
@dataclass
class ProjectConfig:
    name: str                              # Project name
    compose_files: List[str]               # Base compose files
    default_env: str = "dev"               # Default environment
    env_compose_pattern: Optional[str]     # Pattern like "docker-compose.{env}.yml"
```

### CommandContext

Passed to all command handlers:

```python
ctx.config          # ProjectConfig instance
ctx.environment     # Current environment (dev/prod)
ctx.project_dir     # Path to project root
ctx.args            # Parsed argparse.Namespace

# Methods
ctx.get_compose_cmd()                    # Get base compose command list
ctx.compose(*args, **kwargs)             # Run docker compose command
ctx.is_service_running(service: str)     # Check if service is running
ctx.require_service_running(service)     # Exit if service not running
ctx.get_running_services()               # List running services
```

### Decorators

```python
@register_command(name, help="...", arguments=[...])
def cmd_name(ctx: CommandContext) -> None:
    pass

@register_subcommand(parent, name, help="...", arguments=[...])
def cmd_parent_name(ctx: CommandContext) -> None:
    pass
```

### Argument Specification

Arguments use the same format as argparse:

```python
arguments=[
    {"args": ["positional"], "help": "A positional arg"},
    {"args": ["-s", "--short"], "help": "Short and long flag"},
    {"args": ["--flag"], "action": "store_true", "help": "Boolean flag"},
    {"args": ["--count"], "type": int, "default": 10, "help": "Integer with default"},
    {"args": ["items"], "nargs": "*", "help": "Multiple items"},
]
```

### Utility Functions

```python
print_status(message)    # Blue [INFO] prefix
print_success(message)   # Green [SUCCESS] prefix
print_warning(message)   # Yellow [WARNING] prefix (to stderr)
print_error(message)     # Red [ERROR] prefix (to stderr)
fatal(message, code=1)   # Print error and exit
confirm(prompt) -> bool  # Prompt for y/N confirmation
run(cmd, check=True, capture_output=False, env=None, cwd=None)
```

## Examples

### Database Backup Command

```python
@register_command(
    "backup",
    help="Create database backup",
    arguments=[
        {"args": ["-o", "--output"], "help": "Output file path"},
    ]
)
def cmd_backup(ctx: CommandContext) -> None:
    ctx.require_service_running("db")
    
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = ctx.args.output or f"backup_{timestamp}.sql"
    
    print_status(f"Creating backup: {output}")
    ctx.compose("exec", "-T", "db", "pg_dump", "-U", "postgres", ">", output)
    print_success(f"Backup created: {output}")
```

### Grouped Subcommands

```python
@register_command("db", help="Database commands")
def cmd_db(ctx: CommandContext) -> None:
    pass  # Parent command, subcommands do the work

@register_subcommand("db", "migrate", help="Run migrations")
def cmd_db_migrate(ctx: CommandContext) -> None:
    ctx.compose("exec", "web", "npm", "run", "migrate")

@register_subcommand("db", "seed", help="Seed database")
def cmd_db_seed(ctx: CommandContext) -> None:
    ctx.compose("exec", "web", "npm", "run", "seed")
```

Usage:
```bash
./scripts/manage.py db migrate
./scripts/manage.py db seed
```

## License

MIT License
