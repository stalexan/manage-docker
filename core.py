#!/usr/bin/env python3
"""
Docker Container Management Script

Provides common commands for managing Docker Compose projects with plugin support.
Each project can customize behavior through a manage_plugins.py file.

Usage:
    ./manage.py <command> [options]

Environment:
    ENVIRONMENT - Set to 'prod' for production, defaults to 'dev'
"""

import argparse
import importlib.util
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class ProjectConfig:
    """Project-specific configuration."""
    name: str
    compose_files: List[str] = field(default_factory=lambda: ["docker-compose.yml"])
    default_env: str = "dev"
    env_compose_pattern: Optional[str] = None  # e.g., "docker-compose.{env}.yml"

    def get_compose_files(self, env: str) -> List[str]:
        """Get list of compose files for the given environment."""
        files = list(self.compose_files)
        if self.env_compose_pattern:
            files.append(self.env_compose_pattern.format(env=env))
        return files


# Global registry for commands
_command_registry: Dict[str, dict] = {}
_subcommand_registry: Dict[str, Dict[str, dict]] = {}


def register_command(
    name: str,
    help: str = "",
    arguments: Optional[List[dict]] = None,
):
    """
    Decorator to register a plugin command.

    Example:
        @register_command("my-cmd", help="Do something", arguments=[
            {"args": ["-v", "--verbose"], "action": "store_true", "help": "Verbose output"},
        ])
        def cmd_my_cmd(ctx: CommandContext) -> None:
            pass
    """
    def decorator(func: Callable):
        _command_registry[name] = {
            "func": func,
            "help": help,
            "arguments": arguments or [],
        }
        return func
    return decorator


def register_subcommand(
    parent: str,
    name: str,
    help: str = "",
    arguments: Optional[List[dict]] = None,
):
    """
    Decorator to register a plugin subcommand.

    Example:
        @register_subcommand("db", "create-user", help="Create user", arguments=[
            {"args": ["--email"], "required": True, "help": "Email address"},
        ])
        def cmd_db_create_user(ctx: CommandContext) -> None:
            pass
    """
    def decorator(func: Callable):
        if parent not in _subcommand_registry:
            _subcommand_registry[parent] = {}
        _subcommand_registry[parent][name] = {
            "func": func,
            "help": help,
            "arguments": arguments or [],
        }
        return func
    return decorator


# =============================================================================
# UTILITIES
# =============================================================================

class Colors:
    """ANSI color codes for terminal output."""
    CYAN = '\033[36m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    RED = '\033[31m'
    BLUE = '\033[34m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def print_status(message: str) -> None:
    """Print an informational status message."""
    print(f"{Colors.BLUE}[INFO]{Colors.RESET} {message}")


def print_success(message: str) -> None:
    """Print a success message."""
    print(f"{Colors.GREEN}[SUCCESS]{Colors.RESET} {message}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    print(f"{Colors.YELLOW}[WARNING]{Colors.RESET} {message}", file=sys.stderr)


def print_error(message: str) -> None:
    """Print an error message."""
    print(f"{Colors.RED}[ERROR]{Colors.RESET} {message}", file=sys.stderr)


def fatal(message: str, exit_code: int = 1) -> None:
    """Print an error message and exit."""
    print_error(message)
    sys.exit(exit_code)


def confirm(prompt: str) -> bool:
    """Prompt user for confirmation. Returns True if user confirms."""
    try:
        ans = input(f"{prompt} [y/N]: ").strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")


def run(
    cmd: List[str],
    check: bool = True,
    capture_output: bool = False,
    env: Optional[dict] = None,
    cwd: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    """
    Run a command and return the result.

    Args:
        cmd: Command and arguments to run
        check: If True, raise CalledProcessError on non-zero exit
        capture_output: If True, capture stdout/stderr
        env: Environment variables to set
        cwd: Working directory for the command

    Returns:
        CompletedProcess instance
    """
    print_status(f"Running: {' '.join(cmd)}")
    try:
        if capture_output:
            return subprocess.run(
                cmd, check=check, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, cwd=cwd
            )
        return subprocess.run(cmd, check=check, env=env, cwd=cwd)
    except subprocess.CalledProcessError as e:
        if capture_output and e.stdout:
            print(e.stdout)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        raise


# =============================================================================
# DOCKER UTILITIES
# =============================================================================

def check_docker() -> None:
    """Verify Docker is installed and running."""
    try:
        subprocess.run(
            ["docker", "info"],
            check=True, capture_output=True
        )
    except FileNotFoundError:
        fatal("Docker is not installed or not in PATH")
    except subprocess.CalledProcessError:
        fatal("Docker daemon is not running")


def check_compose() -> None:
    """Verify Docker Compose is available."""
    try:
        subprocess.run(
            ["docker", "compose", "version"],
            check=True, capture_output=True
        )
    except subprocess.CalledProcessError:
        fatal("Docker Compose is not installed or not working")


# =============================================================================
# CONTEXT
# =============================================================================

@dataclass
class CommandContext:
    """Context passed to all command handlers."""
    config: ProjectConfig
    environment: str
    project_dir: Path
    args: argparse.Namespace

    def get_compose_cmd(self) -> List[str]:
        """Get the base docker compose command with project-specific files."""
        cmd = ["docker", "compose"]
        for f in self.config.get_compose_files(self.environment):
            filepath = self.project_dir / f
            # Include files that exist or are part of base config
            if filepath.exists():
                cmd.extend(["-f", f])
            elif "{env}" not in f and f in self.config.compose_files:
                # Base compose files should always be included
                cmd.extend(["-f", f])
        return cmd

    def compose(self, *args: str, **kwargs) -> subprocess.CompletedProcess:
        """Run a docker compose command."""
        cmd = self.get_compose_cmd() + list(args)
        return run(cmd, cwd=self.project_dir, **kwargs)

    def is_service_running(self, service: str) -> bool:
        """Check if a service is running."""
        try:
            cp = self.compose(
                "ps", "--services", "--status", "running",
                capture_output=True, check=False
            )
            running = [s.strip() for s in (cp.stdout or "").splitlines()]
            return service in running
        except Exception:
            return False

    def require_service_running(self, service: str) -> None:
        """Require a service to be running, exit if not."""
        if not self.is_service_running(service):
            fatal(f"Service '{service}' is not running. Start with: ./manage.py up")

    def get_running_services(self) -> List[str]:
        """Get list of running services."""
        try:
            cp = self.compose(
                "ps", "--services", "--status", "running",
                capture_output=True, check=False
            )
            return [s.strip() for s in (cp.stdout or "").splitlines() if s.strip()]
        except Exception:
            return []


# =============================================================================
# COMMON COMMANDS
# =============================================================================

def cmd_build(ctx: CommandContext) -> None:
    """Build images without pulling or using cache."""
    cmd = ["build"]
    if ctx.args.service:
        cmd.extend(ctx.args.service)
    ctx.compose(*cmd)
    print_success("Build completed")


def cmd_rebuild(ctx: CommandContext) -> None:
    """Full rebuild with --pull and --no-cache."""
    cmd = ["build", "--pull", "--no-cache"]
    if ctx.args.service:
        cmd.extend(ctx.args.service)
    ctx.compose(*cmd)
    print_success("Rebuild completed")


def cmd_up(ctx: CommandContext) -> None:
    """Start containers in detached mode."""
    cmd = ["up", "-d"]
    if ctx.args.service:
        cmd.extend(ctx.args.service)
    ctx.compose(*cmd)
    print_success("Containers started")


def cmd_down(ctx: CommandContext) -> None:
    """Stop containers."""
    cmd = ["down"]
    if ctx.args.volumes:
        cmd.append("-v")
    if ctx.args.remove_orphans:
        cmd.append("--remove-orphans")
    ctx.compose(*cmd)
    print_success("Containers stopped")


def cmd_restart(ctx: CommandContext) -> None:
    """Restart containers."""
    cmd = ["restart"]
    if ctx.args.service:
        cmd.extend(ctx.args.service)
    ctx.compose(*cmd)
    print_success("Containers restarted")


def cmd_status(ctx: CommandContext) -> None:
    """Show container status."""
    ctx.compose("ps")


def cmd_logs(ctx: CommandContext) -> None:
    """Show container logs."""
    cmd = ["logs"]
    if ctx.args.follow:
        cmd.append("--follow")
    if ctx.args.timestamps:
        cmd.append("--timestamps")
    if ctx.args.tail:
        cmd.extend(["--tail", ctx.args.tail])
    if ctx.args.since:
        cmd.extend(["--since", ctx.args.since])
    if ctx.args.service:
        cmd.extend(ctx.args.service)
    ctx.compose(*cmd)


def cmd_shell(ctx: CommandContext) -> None:
    """Open shell in a container."""
    service = ctx.args.service
    if not service:
        fatal("--service is required. Specify which container to open a shell in.")

    compose_cmd = ctx.get_compose_cmd()
    # Try bash first, then sh
    for shell in ["bash", "sh"]:
        try:
            cmd = compose_cmd + ["exec", "-it", service, shell]
            # Use execvp to replace current process and attach TTY
            os.chdir(ctx.project_dir)
            os.execvp(cmd[0], cmd)
        except FileNotFoundError:
            fatal(f"Command not found: {cmd[0]}")
        except OSError:
            # Shell not available, try next
            continue
    fatal("Failed to start shell (neither bash nor sh available in container)")


def cmd_clean(ctx: CommandContext) -> None:
    """Clean up Docker resources."""
    if ctx.args.all:
        msg = "This will remove ALL containers, networks, images, and volumes for this project!"
    elif ctx.args.volumes:
        msg = "This will prune unused containers, networks, images, and volumes."
    else:
        msg = "This will prune unused containers, networks, and images."

    if not ctx.args.yes:
        if not confirm(msg + " Continue?"):
            print("Aborted.")
            return

    if ctx.args.all:
        # Full cleanup - stop and remove everything including volumes
        ctx.compose("down", "-v", "--remove-orphans")

    # Prune system resources
    run(["docker", "system", "prune", "-f"])
    if ctx.args.volumes or ctx.args.all:
        run(["docker", "volume", "prune", "-f"])

    print_success("Cleanup completed")


def cmd_stats(ctx: CommandContext) -> None:
    """Show container resource usage."""
    if ctx.args.no_stream:
        run(["docker", "stats", "--no-stream", "--format",
             "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"])
    else:
        run(["docker", "stats"])


# =============================================================================
# ARGUMENT PARSER
# =============================================================================

def _add_arguments_from_list(parser: argparse.ArgumentParser, arguments: List[dict]) -> None:
    """Add arguments to parser from a list of argument specifications."""
    for arg in arguments:
        # Make a copy to avoid modifying the original
        arg_copy = dict(arg)
        args = arg_copy.pop("args", [])
        if args:
            parser.add_argument(*args, **arg_copy)


def build_parser(config: ProjectConfig) -> argparse.ArgumentParser:
    """Build the argument parser with common and plugin commands."""
    parser = argparse.ArgumentParser(
        description=f"Manage Docker containers for {config.name}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--env", "-e",
        default=os.environ.get("ENVIRONMENT", config.default_env),
        help=f"Environment (default: {config.default_env}, or set ENVIRONMENT env var)",
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    # -------------------------------------------------------------------------
    # Common commands
    # -------------------------------------------------------------------------

    # build
    p = sub.add_parser("build", help="Build images")
    p.add_argument("service", nargs="*", help="Service(s) to build")
    p.set_defaults(func=cmd_build)

    # rebuild
    p = sub.add_parser("rebuild", help="Full rebuild with --pull --no-cache")
    p.add_argument("service", nargs="*", help="Service(s) to rebuild")
    p.set_defaults(func=cmd_rebuild)

    # up
    p = sub.add_parser("up", help="Start containers (detached)")
    p.add_argument("service", nargs="*", help="Service(s) to start")
    p.set_defaults(func=cmd_up)

    # down
    p = sub.add_parser("down", help="Stop containers")
    p.add_argument("-v", "--volumes", action="store_true",
                   help="Remove named volumes")
    p.add_argument("--remove-orphans", action="store_true",
                   help="Remove orphan containers")
    p.set_defaults(func=cmd_down)

    # restart
    p = sub.add_parser("restart", help="Restart containers")
    p.add_argument("service", nargs="*", help="Service(s) to restart")
    p.set_defaults(func=cmd_restart)

    # status
    p = sub.add_parser("status", help="Show container status")
    p.set_defaults(func=cmd_status)

    # logs
    p = sub.add_parser("logs", help="Show container logs")
    p.add_argument("service", nargs="*", help="Service(s) to show logs for")
    p.add_argument("-f", "--follow", action="store_true",
                   help="Follow log output")
    p.add_argument("--timestamps", action="store_true",
                   help="Show timestamps")
    p.add_argument("--tail", metavar="N",
                   help="Number of lines to show (e.g., '100')")
    p.add_argument("--since",
                   help="Show logs since timestamp (e.g., '5m', '2021-01-02T13:23:00')")
    p.set_defaults(func=cmd_logs)

    # shell
    p = sub.add_parser("shell", help="Open shell in a container")
    p.add_argument("--service", "-s", required=True,
                   help="Service to open shell in (required)")
    p.set_defaults(func=cmd_shell)

    # clean
    p = sub.add_parser("clean", help="Clean up Docker resources")
    p.add_argument("-y", "--yes", action="store_true",
                   help="Skip confirmation prompt")
    p.add_argument("--volumes", action="store_true",
                   help="Also prune unused volumes")
    p.add_argument("--all", action="store_true",
                   help="Remove everything including project volumes (destructive)")
    p.set_defaults(func=cmd_clean)

    # stats
    p = sub.add_parser("stats", help="Show container resource usage")
    p.add_argument("--no-stream", action="store_true",
                   help="Show snapshot instead of live stream")
    p.set_defaults(func=cmd_stats)

    # -------------------------------------------------------------------------
    # Plugin commands
    # -------------------------------------------------------------------------
    for name, info in _command_registry.items():
        p = sub.add_parser(name, help=info["help"])
        _add_arguments_from_list(p, info.get("arguments", []))
        p.set_defaults(func=info["func"])

        # Add subcommands if any exist for this command
        if name in _subcommand_registry:
            subsub = p.add_subparsers(dest=f"{name}_subcommand", required=True, metavar="<subcommand>")
            for subname, subinfo in _subcommand_registry[name].items():
                sp = subsub.add_parser(subname, help=subinfo["help"])
                _add_arguments_from_list(sp, subinfo.get("arguments", []))
                sp.set_defaults(func=subinfo["func"])

    return parser


# =============================================================================
# PLUGIN LOADING
# =============================================================================

def load_plugins(script_path: Path) -> Optional[ProjectConfig]:
    """
    Load plugins from manage_plugins.py in the same directory as the entry script.

    Returns:
        ProjectConfig from the plugins module, or None if not found
    """
    plugins_file = script_path.parent / "manage_plugins.py"

    if not plugins_file.exists():
        return None

    spec = importlib.util.spec_from_file_location("manage_plugins", plugins_file)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules["manage_plugins"] = module
    spec.loader.exec_module(module)

    # Return config from module
    return getattr(module, "config", None)


# =============================================================================
# MAIN
# =============================================================================

def main(script_path: Optional[Path] = None) -> int:
    """
    Main entry point for the management script.

    Args:
        script_path: Path to the entry script (used to locate plugins)

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    if script_path is None:
        script_path = Path(sys.argv[0]).resolve()

    # Determine project directory
    # If script is in scripts/ subdirectory, go up one level
    project_dir = script_path.parent
    if project_dir.name == "scripts":
        project_dir = project_dir.parent

    # Verify Docker is available
    check_docker()
    check_compose()

    # Load plugins and get config
    config = load_plugins(script_path)
    if config is None:
        config = ProjectConfig(name=project_dir.name)

    # Build parser and parse args
    parser = build_parser(config)
    args = parser.parse_args()

    # Create context
    ctx = CommandContext(
        config=config,
        environment=args.env,
        project_dir=project_dir,
        args=args,
    )

    # Change to project directory for relative path operations
    os.chdir(project_dir)

    try:
        args.func(ctx)
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except subprocess.CalledProcessError as e:
        return e.returncode if e.returncode else 1
    except SystemExit as e:
        return int(getattr(e, "code", 1) or 0)


if __name__ == "__main__":
    sys.exit(main())
