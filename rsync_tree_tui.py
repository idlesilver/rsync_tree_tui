#!/usr/bin/env python3

from __future__ import annotations

import argparse
import atexit
import concurrent.futures
import curses
from datetime import datetime
import grp
import hashlib
import json
import os
import pwd
import re
import signal
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# ------------------------------------------------------------------------ #
#                                  config                                  #
# ------------------------------------------------------------------------ #

APP_NAME = "rsync-tree-tui"
__version__ = "0.2.10"
GITHUB_RAW_URL = "https://raw.githubusercontent.com/idlesilver/rsync_tree_tui/main/rsync_tree_tui.py"
GITHUB_VERSION_URL = "https://raw.githubusercontent.com/idlesilver/rsync_tree_tui/main/VERSION"
AUTO_UPDATE_VERSION_TIMEOUT = 2
UPDATE_PAYLOAD_TIMEOUT = 10
CONFIG_VERSION = 1
LOCAL_ROOT_ENV = "RSYNC_TREE_TUI_LOCAL_ROOT"
REMOTE_ENV = "RSYNC_TREE_TUI_REMOTE"
PERMISSION_GROUP_ENV = "RSYNC_TREE_TUI_PERMISSION_GROUP"
DEFAULT_CHECKSUM_THRESHOLD_MB = 512
DEFAULT_CHECKSUM_SUFFIXES = [
    ".json",
    ".yaml",
    ".yml",
    ".txt",
    ".py",
    ".sh",
    ".md",
]
DEFAULT_PAGINATION_SIZE = 20
DEFAULT_ESC_DELAY_MS = 25
DEFAULT_MOUSE_WHEEL_STEP = 1
DEFAULT_MOUSE_WHEEL_COALESCE_MS = 0
MIN_MAIN_RENDER_WIDTH = 34
MIN_MAIN_RENDER_HEIGHT = 8
DIM_TEXT_COLOR_256 = 244
DEFAULT_DIFF_VIEWERS = ["vim -d {local} {remote}"]
DEFAULT_FILE_EDITOR = "vim {file}"
DEFAULT_IMAGE_OPENER = (
    "sh -c 'timg \"$1\" && printf \"\\nPress Ctrl+C to return to rsync-tree-tui...\\n\" "
    "&& sleep 2147483647' timg-view {file}"
)
IMAGE_FILE_SUFFIXES = {
    ".apng",
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
SYSTEM_FILE_OPENERS = {
    "darwin": "open {file}",
    "linux": "xdg-open {file}",
    "win32": "start {file}",
}
ANSI_GREEN = "\033[32m"
ANSI_CYAN = "\033[36m"
ANSI_YELLOW = "\033[33m"
ANSI_DIM = "\033[2m"
ANSI_RESET = "\033[0m"


def default_config_path() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    config_home = Path(xdg_config_home).expanduser() if xdg_config_home else Path.home() / ".config"
    return config_home / APP_NAME / "config.json"


def default_config_data() -> dict[str, object]:
    return {
        "version": CONFIG_VERSION,
        "auto_update": {
            "enabled": True,
            "skipped_version": "",
            "latest_version": "",
            "latest_checked_at": "",
            "last_prompted_version": "",
            "last_prompted_at": "",
        },
        "checksum_policy": {
            "mode": "balanced",
            "size_threshold_mb": DEFAULT_CHECKSUM_THRESHOLD_MB,
            "checksum_suffixes": DEFAULT_CHECKSUM_SUFFIXES,
        },
        "diff_viewers": DEFAULT_DIFF_VIEWERS,
        "file_editor": DEFAULT_FILE_EDITOR,
        "image_opener": DEFAULT_IMAGE_OPENER,
        "mouse_wheel": {
            "step": DEFAULT_MOUSE_WHEEL_STEP,
            "coalesce_ms": DEFAULT_MOUSE_WHEEL_COALESCE_MS,
        },
        "permission_group": "",
        "known_connections": [],
    }


def load_json_config(config_path: Path) -> dict[str, object]:
    if not config_path.exists():
        data = default_config_data()
        save_json_config(config_path, data)
        return data

    data = json.loads(config_path.read_text())
    changed = False
    default_data = default_config_data()
    for key, default_value in default_data.items():
        if key not in data:
            data[key] = default_value
            changed = True
        elif isinstance(default_value, dict):
            if not isinstance(data[key], dict):
                data[key] = default_value
                changed = True
                continue
            for nested_key, nested_default_value in default_value.items():
                if nested_key not in data[key]:
                    data[key][nested_key] = nested_default_value
                    changed = True
    if changed:
        save_json_config(config_path, data)
    return data


def save_json_config(config_path: Path, data: dict[str, object]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def configure_escape_delay(delay_ms: int = DEFAULT_ESC_DELAY_MS) -> None:
    if hasattr(curses, "set_escdelay"):
        curses.set_escdelay(delay_ms)
    else:
        os.environ.setdefault("ESCDELAY", str(delay_ms))


def read_dotenv(env_file: Path) -> dict[str, str]:
    if not env_file.exists():
        return {}

    env: dict[str, str] = {}
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip("\"'")
    return env


def get_env_or_dotenv(key: str, dotenv: dict[str, str]) -> str | None:
    val = os.environ.get(key)
    if val:
        return val
    return dotenv.get(key)


def get_local_root_value(
    args: argparse.Namespace,
    dotenv: dict[str, str],
    dotenv_base_dir: Path,
    cwd: Path,
) -> tuple[str | Path | None, Path]:
    if args.local_root is not None:
        return args.local_root, cwd
    val = os.environ.get(LOCAL_ROOT_ENV)
    if val:
        return val, cwd
    if dotenv.get(LOCAL_ROOT_ENV):
        return dotenv[LOCAL_ROOT_ENV], dotenv_base_dir
    return None, cwd


def get_remote_value(
    args: argparse.Namespace,
    dotenv: dict[str, str],
    dotenv_base_dir: Path,
    cwd: Path,
) -> tuple[str | None, Path]:
    if args.remote is not None:
        return str(args.remote), cwd
    val = os.environ.get(REMOTE_ENV)
    if val:
        return val, cwd
    if dotenv.get(REMOTE_ENV):
        return dotenv[REMOTE_ENV], dotenv_base_dir
    return None, cwd


def resolve_local_root(value: str | Path | None, cwd: Path) -> Path:
    if value is None:
        return cwd.resolve()
    path = Path(value).expanduser()
    return (path if path.is_absolute() else cwd / path).resolve()


def remote_spec_is_local(remote_spec: str) -> bool:
    return (
        ":" not in remote_spec
        or remote_spec.startswith("/")
        or remote_spec.startswith("./")
        or remote_spec.startswith("../")
        or remote_spec.startswith("~")
    )


def split_remote_spec(remote_spec: str) -> tuple[str, str]:
    if ":" not in remote_spec:
        raise ValueError(f"Invalid remote spec: {remote_spec}")
    remote_target, remote_root = remote_spec.split(":", 1)
    if not remote_target or not remote_root:
        raise ValueError(f"Invalid remote spec: {remote_spec}")
    return remote_target, remote_root


def resolve_remote_spec(value: str, base_dir: Path) -> tuple[str, bool]:
    if not value:
        raise ValueError("Remote spec is empty")
    if not remote_spec_is_local(value):
        split_remote_spec(value)
        return value, False
    path = Path(value).expanduser()
    resolved = (path if path.is_absolute() else base_dir / path).resolve()
    return str(resolved), True


def validate_local_remote_roots(local_root: Path, remote_root: Path) -> None:
    local_resolved = local_root.resolve()
    remote_resolved = remote_root.resolve()
    if local_resolved == remote_resolved:
        raise ValueError(f"Local root and remote path are the same: {local_resolved}")
    common = os.path.commonpath([str(local_resolved), str(remote_resolved)])
    if common == str(local_resolved) or common == str(remote_resolved):
        raise ValueError(
            "Local root and local remote path must not be nested: "
            f"{local_resolved} <-> {remote_resolved}"
        )


def connection_id(local_root: Path, remote: str) -> str:
    payload = f"{local_root.resolve()}\0{remote}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:8]


def sorted_known_connections(config_data: dict[str, object]) -> list[dict[str, object]]:
    entries = config_data.get("known_connections", [])
    if not isinstance(entries, list):
        return []
    return sorted(
        (entry for entry in entries if isinstance(entry, dict)),
        key=lambda entry: int(entry.get("trigger_count", 0)),
        reverse=True,
    )


def use_ansi_color() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def color_text(text: str, color: str, use_color: bool) -> str:
    if not use_color or not text:
        return text
    return f"{color}{text}{ANSI_RESET}"


def split_remote_for_display(remote: str) -> tuple[str, str, str]:
    if remote_spec_is_local(remote):
        return "", remote, ""
    target, separator, path = remote.partition(":")
    if not separator:
        return "", target, ""
    user, at, host = target.partition("@")
    if not at:
        return "", target, f":{path}"
    return user, host, f":{path}"


def format_remote_for_display(remote: str, use_color: bool) -> str:
    user, host, path = split_remote_for_display(remote)
    if user:
        return (
            f"{color_text(user, ANSI_GREEN, use_color)}@"
            f"{color_text(host, ANSI_CYAN, use_color)}"
            f"{color_text(path, ANSI_YELLOW, use_color)}"
        )
    return (
        f"{color_text(host, ANSI_CYAN, use_color)}"
        f"{color_text(path, ANSI_YELLOW, use_color)}"
    )


def format_known_connection_entry(
    index: int,
    entry: dict[str, object],
    use_color: bool,
) -> str:
    trigger_count = int(entry.get("trigger_count", 0))
    local_root = str(entry.get("local_root", ""))
    remote = str(entry.get("remote", ""))
    runs_text = color_text(f"({trigger_count} runs)", ANSI_DIM, use_color)
    return (
        f"  [{index}] {local_root}  <->  "
        f"{format_remote_for_display(remote, use_color)}  {runs_text}"
    )


def choose_known_connection(config_data: dict[str, object]) -> dict[str, object]:
    entries = sorted_known_connections(config_data)
    if not entries:
        print(
            "Error: --remote is required because no known connections exist yet."
        )
        raise SystemExit(1)

    print("Known rsync-tree-tui connections:")
    color_enabled = use_ansi_color()
    for index, entry in enumerate(entries):
        print(format_known_connection_entry(index, entry, color_enabled))
    raw_index = input("Select connection index: ").strip()
    index = int(raw_index)
    if index < 0 or index >= len(entries):
        raise IndexError(f"Invalid connection index: {index}")
    return entries[index]


def record_successful_connection(
    config_path: Path,
    config_data: dict[str, object],
    local_root: Path,
    remote: str,
    permission_group: str | None = None,
) -> None:
    entries = config_data.setdefault("known_connections", [])
    if not isinstance(entries, list):
        entries = []
        config_data["known_connections"] = entries

    conn_id = connection_id(local_root, remote)
    for entry in entries:
        if isinstance(entry, dict) and entry.get("id") == conn_id:
            entry["local_root"] = str(local_root.resolve())
            entry["remote"] = remote
            entry["trigger_count"] = int(entry.get("trigger_count", 0)) + 1
            if permission_group:
                entry["permission_group"] = permission_group
            save_json_config(config_path, config_data)
            return

    entry = {
        "id": conn_id,
        "local_root": str(local_root.resolve()),
        "remote": remote,
        "trigger_count": 1,
    }
    if permission_group:
        entry["permission_group"] = permission_group
    entries.append(entry)
    save_json_config(config_path, config_data)


def preflight(local_root: Path, *, require_ssh: bool = True) -> None:
    required_commands = ("ssh", "rsync", "diff", "find") if require_ssh else ("rsync", "diff", "find")
    missing = [cmd for cmd in required_commands if shutil.which(cmd) is None]
    if missing:
        raise RuntimeError(f"Missing required command(s): {', '.join(missing)}")

    subprocess.run(
        ["find", ".", "-maxdepth", "0", "-printf", ""],
        cwd=local_root,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def resolve_app_config(args: argparse.Namespace) -> AppConfig:
    cwd = Path.cwd().resolve()
    env_file = (args.env_file or cwd / ".env").expanduser()
    if not env_file.is_absolute():
        env_file = (cwd / env_file).resolve()
    dotenv = read_dotenv(env_file)
    dotenv_base_dir = env_file.parent

    config_path = args.config or default_config_path()
    config_path = config_path.expanduser()
    if not config_path.is_absolute():
        config_path = (cwd / config_path).resolve()
    config_data = load_json_config(config_path)

    local_value, local_root_base_dir = get_local_root_value(
        args,
        dotenv,
        dotenv_base_dir,
        cwd,
    )
    remote_value, remote_base_dir = get_remote_value(args, dotenv, dotenv_base_dir, cwd)
    cli_permission_group = getattr(args, "permission_group", None)
    env_permission_group = get_env_or_dotenv(PERMISSION_GROUP_ENV, dotenv)

    selected_connection: dict[str, object] | None = None
    if remote_value is None:
        selected_connection = choose_known_connection(config_data)
        remote_value = str(selected_connection["remote"])
        remote_base_dir = cwd

    if local_value is None and selected_connection is not None:
        local_root = resolve_local_root(str(selected_connection["local_root"]), cwd)
    else:
        local_root = resolve_local_root(local_value, local_root_base_dir)
    remote, remote_is_local = resolve_remote_spec(remote_value, remote_base_dir)
    if remote_is_local:
        validate_local_remote_roots(local_root, Path(remote))

    permission_group = ""
    permission_group_source = "none"
    if cli_permission_group:
        permission_group = str(cli_permission_group)
        permission_group_source = "cli"
    elif env_permission_group:
        permission_group = env_permission_group
        permission_group_source = "env/.env"
    elif (
        selected_connection is not None
        and selected_connection.get("permission_group")
    ):
        permission_group = str(selected_connection["permission_group"])
        permission_group_source = "known connection"
    elif config_data.get("permission_group"):
        permission_group = str(config_data["permission_group"])
        permission_group_source = "global config"

    file_editor = resolve_file_editor(config_data)
    return AppConfig(
        local_root=local_root,
        remote_spec=remote,
        remote_is_local=remote_is_local,
        config_path=config_path,
        config_data=config_data,
        checksum_policy=ChecksumPolicy.from_config(config_data),
        diff_viewers=parse_diff_viewers(config_data),
        file_editor=file_editor,
        image_opener=resolve_image_opener(config_data, file_editor),
        mouse_wheel=parse_mouse_wheel_config(config_data),
        permission_group=permission_group,
        permission_group_source=permission_group_source,
        pagination_size=int(config_data.get("pagination_size", DEFAULT_PAGINATION_SIZE)),
    )

# ------------------------------------------------------------------------ #
#                                  models                                  #
# ------------------------------------------------------------------------ #


class EntryType(str, Enum):
    FILE = "file"
    DIRECTORY = "directory"


class SelectionState(str, Enum):
    UNSELECTED = " "
    SELECTED = "x"
    PARTIAL = "-"


@dataclass(slots=True)
class EntryMeta:
    rel_path: str
    entry_type: EntryType
    size: int
    mtime_s: int
    perms: int  # octal mode bits, e.g. 0o755
    owner: str = ""
    group: str = ""


@dataclass(slots=True)
class ChecksumPolicy:
    mode: str
    size_threshold_bytes: int
    checksum_suffixes: set[str]

    @classmethod
    def from_config(cls, config_data: dict[str, object]) -> ChecksumPolicy:
        policy = config_data.get("checksum_policy", {})
        if not isinstance(policy, dict):
            policy = {}
        threshold_mb = int(policy.get("size_threshold_mb", DEFAULT_CHECKSUM_THRESHOLD_MB))
        suffixes = policy.get("checksum_suffixes", DEFAULT_CHECKSUM_SUFFIXES)
        if not isinstance(suffixes, list):
            suffixes = DEFAULT_CHECKSUM_SUFFIXES
        return cls(
            mode=str(policy.get("mode", "balanced")),
            size_threshold_bytes=threshold_mb * 1024 * 1024,
            checksum_suffixes={str(s).lower() for s in suffixes},
        )

    def should_checksum(self, rel_path: str, size: int | None) -> bool:
        if self.mode == "strict":
            return True
        if self.mode == "fast":
            return Path(rel_path).suffix.lower() in self.checksum_suffixes
        if Path(rel_path).suffix.lower() in self.checksum_suffixes:
            return True
        if size is None:
            return False
        return size <= self.size_threshold_bytes


def parse_diff_viewers(config_data: dict[str, object]) -> list[str]:
    value = config_data.get("diff_viewers", DEFAULT_DIFF_VIEWERS)
    if isinstance(value, str):
        viewers = [value]
    elif isinstance(value, list):
        viewers = [str(item) for item in value if str(item).strip()]
    else:
        viewers = DEFAULT_DIFF_VIEWERS
    return viewers or DEFAULT_DIFF_VIEWERS


@dataclass(slots=True)
class MouseWheelConfig:
    step: int
    coalesce_ms: int


def _parse_int_config(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_mouse_wheel_config(config_data: dict[str, object]) -> MouseWheelConfig:
    value = config_data.get("mouse_wheel", {})
    if not isinstance(value, dict):
        value = {}
    step = _parse_int_config(value.get("step"), DEFAULT_MOUSE_WHEEL_STEP)
    coalesce_ms = _parse_int_config(
        value.get("coalesce_ms"),
        DEFAULT_MOUSE_WHEEL_COALESCE_MS,
    )
    return MouseWheelConfig(
        step=max(1, step),
        coalesce_ms=max(0, coalesce_ms),
    )


def is_supported_external_diff_viewer(command: str) -> bool:
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    if not argv:
        return False

    executable = Path(argv[0]).name
    if executable == "delta":
        return True
    if executable == "vimdiff":
        return True
    if executable in {"vim", "nvim"} and "-d" in argv[1:]:
        return True
    return False


@dataclass(slots=True)
class FileEditor:
    command: str
    can_modify: bool
    source: str
    wait: bool = True


def resolve_file_editor(
    config_data: dict[str, object],
    *,
    environ: dict[str, str] | os._Environ[str] | None = None,
    platform: str | None = None,
) -> FileEditor:
    env = os.environ if environ is None else environ
    configured = config_data.get("file_editor")
    if isinstance(configured, str) and configured.strip():
        command = configured.strip()
        if command != DEFAULT_FILE_EDITOR or shutil.which("vim") is not None:
            return FileEditor(command, True, "config")

    for env_name in ("VISUAL", "EDITOR"):
        value = env.get(env_name)
        if value:
            return FileEditor(f"{value} {{file}}", True, f"${env_name}")

    platform_name = platform or sys.platform
    command = SYSTEM_FILE_OPENERS.get(platform_name)
    if command is None and platform_name.startswith("linux"):
        command = SYSTEM_FILE_OPENERS["linux"]
    if command is None:
        command = "vi {file}"
        return FileEditor(command, True, "fallback")
    return FileEditor(command, False, "system opener", wait=False)


def resolve_image_opener(
    config_data: dict[str, object],
    file_editor: FileEditor,
) -> FileEditor:
    configured = config_data.get("image_opener", DEFAULT_IMAGE_OPENER)
    command = configured if isinstance(configured, str) and configured.strip() else DEFAULT_IMAGE_OPENER
    command = command.strip()
    try:
        argv = shlex.split(command)
    except ValueError:
        return file_editor
    executable = "timg" if command == DEFAULT_IMAGE_OPENER else argv[0] if argv else ""
    if executable and shutil.which(executable) is not None:
        return FileEditor(command, False, "image_opener")
    return file_editor


def is_image_file_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_FILE_SUFFIXES


def build_file_editor_command(editor: FileEditor, file_path: Path) -> list[str]:
    try:
        argv = shlex.split(editor.command)
    except ValueError as exc:
        raise ValueError(f"Invalid file editor command: {exc}") from exc
    if not argv:
        raise ValueError("Invalid file editor command: empty command")

    format_values = {"file": str(file_path)}
    try:
        command = [part.format(**format_values) for part in argv]
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid file editor placeholder: {exc}") from exc
    if not any("{file}" in part for part in argv):
        command.append(str(file_path))
    return command


@dataclass(slots=True)
class AppConfig:
    local_root: Path
    remote_spec: str
    remote_is_local: bool
    config_path: Path
    config_data: dict[str, object]
    checksum_policy: ChecksumPolicy
    diff_viewers: list[str]
    file_editor: FileEditor
    image_opener: FileEditor
    mouse_wheel: MouseWheelConfig
    permission_group: str = ""
    permission_group_source: str = "none"
    pagination_size: int = DEFAULT_PAGINATION_SIZE


@dataclass(slots=True)
class PermissionRequest:
    mode: str
    rel_paths: list[str]
    permission_group: str


@dataclass(slots=True)
class RemoteEditUploadRequest:
    rel_path: str
    temp_root: Path


PERMISSION_VIEWS = ("badge", "owner", "group", "mode")
PERMISSION_READ_ORDER = ("pvt", "grp", "any")
PERMISSION_WRITE_ORDER = ("pvt", "grp", "any")
PERMISSION_SCOPE_ORDER = PERMISSION_READ_ORDER
LEGACY_PERMISSION_MODE_MAP = {
    "pvt": "pvt:pvt",
    "grp:r": "grp:pvt",
    "grp:w": "grp:grp",
    "any:r": "any:pvt",
    "any:w": "any:any",
}


class PermissionActionInterrupted(Exception):
    pass


@dataclass(slots=True)
class ListLayout:
    row_start: int
    list_height: int
    selection_width: int
    panel_width: int
    divider_width: int
    badge_width: int = 7

    def visible_index_at(self, y: int, scroll_offset: int, visible_count: int) -> int | None:
        if y < self.row_start or y >= self.row_start + self.list_height:
            return None
        visible_index = scroll_offset + y - self.row_start
        if visible_index < 0 or visible_index >= visible_count:
            return None
        return visible_index

    def is_selection_column(self, x: int) -> bool:
        return 0 <= x < self.selection_width


@dataclass(slots=True)
class FooterShortcutHit:
    y: int
    start_x: int
    end_x: int
    key: int

    def contains(self, x: int, y: int) -> bool:
        return self.y == y and self.start_x <= x < self.end_x


# ------------------------------------------------------------------------ #
#                              manifest helpers                             #
# ------------------------------------------------------------------------ #


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive local/remote tree comparison and rsync tool.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Defaults (in priority order):\n"
            f"  --local-root : ${LOCAL_ROOT_ENV} → .env {LOCAL_ROOT_ENV} → current pwd\n"
            f"  --remote     : ${REMOTE_ENV} → .env {REMOTE_ENV} → known connection picker\n"
            f"  --permission-group : ${PERMISSION_GROUP_ENV} → .env → known connection → config\n"
            f"  --config     : {default_config_path()}\n"
        ),
    )
    parser.add_argument(
        "--local-root",
        type=Path,
        default=None,
        help="Local root (default: env / .env / current working directory).",
    )
    parser.add_argument(
        "--remote",
        default=None,
        help="Remote target user@host:/path (default: env / .env / known config picker).",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Dotenv file to read after terminal environment variables (default: ./.env).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"Global JSON config path (default: {default_config_path()}).",
    )
    parser.add_argument(
        "--permission-group",
        default=None,
        help=(
            "Optional selected group for grp:* permission changes "
            f"(default: ${PERMISSION_GROUP_ENV} / .env / known config / global config)."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} {__version__}",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update to the latest version from GitHub.",
    )
    return parser.parse_args()


def extract_version_from_source(source: str) -> str | None:
    """Extract __version__ value from Python source code.

    Returns None if version cannot be determined.
    """
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    return match.group(1) if match else None


@dataclass(frozen=True, slots=True)
class RemoteUpdateSource:
    source: str
    version: str | None


class UpdateError(RuntimeError):
    pass


def semver_numeric_tuple(version: str) -> tuple[int, int, int] | None:
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$", version.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def compare_semver_versions(left: str, right: str) -> int | None:
    left_tuple = semver_numeric_tuple(left)
    right_tuple = semver_numeric_tuple(right)
    if left_tuple is None or right_tuple is None:
        return None
    if left_tuple > right_tuple:
        return 1
    if left_tuple < right_tuple:
        return -1
    return 0


def decode_update_response(response: object) -> str:
    try:
        return response.read().decode("utf-8")  # type: ignore[attr-defined]
    except UnicodeDecodeError as e:
        raise UpdateError("Remote payload is not valid UTF-8") from e
    except OSError as e:
        raise UpdateError(f"Remote payload could not be read - {e}") from e


def check_update_response_status(response: object) -> None:
    status = getattr(response, "status", 200)
    reason = getattr(response, "reason", "")
    if status != 200:
        raise UpdateError(f"HTTP {status} - {reason}".rstrip())


def download_remote_version(timeout: int = AUTO_UPDATE_VERSION_TIMEOUT) -> str | None:
    try:
        with urllib.request.urlopen(GITHUB_VERSION_URL, timeout=timeout) as response:
            check_update_response_status(response)
            remote_version = decode_update_response(response).strip()
    except (urllib.error.URLError, TimeoutError, OSError, UpdateError):
        return None

    if semver_numeric_tuple(remote_version) is None:
        return None
    return remote_version


def download_remote_update_source(timeout: int = UPDATE_PAYLOAD_TIMEOUT) -> RemoteUpdateSource:
    try:
        with urllib.request.urlopen(GITHUB_RAW_URL, timeout=timeout) as response:
            check_update_response_status(response)
            new_source = decode_update_response(response)
    except urllib.error.URLError as e:
        raise UpdateError(f"Network error - {e.reason}") from e
    except TimeoutError as e:
        raise UpdateError(f"Connection timed out after {timeout} seconds") from e
    except OSError as e:
        raise UpdateError(f"Network error - {e}") from e

    if "__version__" not in new_source or "rsync" not in new_source.lower():
        raise UpdateError("Downloaded content does not appear to be a valid script")

    return RemoteUpdateSource(
        source=new_source,
        version=extract_version_from_source(new_source),
    )


def install_remote_update(remote_version: str | None = None) -> str | None:
    remote_source = download_remote_update_source()
    source_version = remote_source.version
    if remote_version and source_version != remote_version:
        raise UpdateError(
            f"Downloaded payload version {source_version or 'unknown'} "
            f"does not match expected version {remote_version}"
        )
    install_update_source(remote_source.source, Path(sys.argv[0]).resolve())
    return source_version


def install_update_source(new_source: str, current_path: Path) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        tmp_path = Path(f.name)
        f.write(new_source)

    try:
        try:
            tmp_path.chmod(current_path.stat().st_mode)
        except OSError:
            tmp_path.chmod(0o755)

        os.replace(tmp_path, current_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def perform_self_update() -> None:
    """Download and install the latest version from GitHub.

    This function handles the complete update process:
    1. Download latest version from GitHub
    2. Validate the downloaded content
    3. Compare versions
    4. Ask user confirmation before replacing
    5. Replace the current script file
    6. Exit with appropriate status message
    """
    current_path = Path(sys.argv[0]).resolve()
    print(f"{APP_NAME} {__version__} - Self Update")
    print("-" * 40)

    print("Checking latest version from GitHub...")
    new_version = download_remote_version()
    if not new_version:
        print("No update installed: remote version could not be checked.")
        print("Start again without --update to use the current version.")
        raise SystemExit(0)

    print(f"Remote version: {new_version}")
    version_comparison = compare_semver_versions(new_version, __version__)
    if version_comparison != 1:
        print("Already up to date. No files were changed.")
        print("Start again without --update to use the current version.")
        raise SystemExit(0)

    print(f"\nCurrent: {__version__} → Remote: {new_version}")
    try:
        answer = input("Update? [y/N] ").strip().lower()
    except EOFError:
        answer = "n"

    if answer not in ("y", "yes"):
        print("Cancelled. No files were changed.")
        print("Start again without --update to use the current version.")
        raise SystemExit(0)

    print("Downloading update payload from GitHub...")
    try:
        installed_version = install_remote_update(new_version)
        print(f"Updated: {current_path}")
        print(f"Successfully updated to version {installed_version or new_version}")
        print("Please restart the application to use the new version.")
        raise SystemExit(0)
    except UpdateError as e:
        print(f"Error: {e}")
        print("No files were replaced.")
        print("Start again without --update or choose not to update at startup.")
        raise SystemExit(1)
    except PermissionError:
        print(f"Error: Permission denied - cannot write to {current_path}")
        print("No files were replaced.")
        print("Start again without --update or choose not to update at startup.")
        raise SystemExit(1)


def auto_update_config(config_data: dict[str, object]) -> dict[str, object]:
    default_auto_update = default_config_data()["auto_update"]
    value = config_data.get("auto_update")
    if not isinstance(value, dict):
        value = dict(default_auto_update)
        config_data["auto_update"] = value
    for key, default_value in default_auto_update.items():
        value.setdefault(key, default_value)
    return value


def current_local_iso8601() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def record_latest_remote_version(
    config_path: Path,
    remote_version: str,
) -> None:
    config_data = load_json_config(config_path)
    config = auto_update_config(config_data)
    config["latest_version"] = remote_version
    config["latest_checked_at"] = current_local_iso8601()
    save_json_config(config_path, config_data)


def background_refresh_latest_version(
    config_path: Path,
    config_data: dict[str, object],
) -> None:
    config = auto_update_config(config_data)
    if config.get("enabled") is False:
        return
    if not sys.stdin.isatty():
        return

    remote_version = download_remote_version()
    if not remote_version:
        return
    if compare_semver_versions(remote_version, __version__) != 1:
        return
    record_latest_remote_version(config_path, remote_version)


def start_background_auto_update_check(
    config_path: Path,
    config_data: dict[str, object],
) -> threading.Thread | None:
    config = auto_update_config(config_data)
    if config.get("enabled") is False:
        return None
    if not sys.stdin.isatty():
        return None

    thread = threading.Thread(
        target=background_refresh_latest_version,
        args=(config_path, config_data),
        daemon=True,
    )
    thread.start()
    return thread


def maybe_prompt_for_cached_auto_update(
    config_path: Path,
    config_data: dict[str, object],
) -> None:
    config = auto_update_config(config_data)
    if config.get("enabled") is False:
        return
    if not sys.stdin.isatty():
        return

    remote_version = str(config.get("latest_version") or "")
    if not remote_version:
        return
    if compare_semver_versions(remote_version, __version__) != 1:
        return
    if remote_version == config.get("skipped_version"):
        return

    print(f"\nA new {APP_NAME} version is available: {__version__} → {remote_version}")
    print(
        "Choose: [u/y] update, [l/n/Enter] later, "
        "[s] skip this version, [d] disable auto checks"
    )
    try:
        answer = input("Update choice [later]: ").strip().lower()
    except EOFError:
        return

    if answer in ("u", "y", "yes"):
        current_path = Path(sys.argv[0]).resolve()
        try:
            installed_version = install_remote_update(remote_version)
        except UpdateError as e:
            print(f"Error: {e}")
            print("No files were replaced.")
            print("Start again without --update or choose not to update at startup.")
            raise SystemExit(1)
        except OSError as e:
            print(f"Error: {e}")
            print("No files were replaced.")
            print("Start again without --update or choose not to update at startup.")
            raise SystemExit(1)
        print(f"Updated: {current_path}")
        print(f"Successfully updated to version {installed_version or remote_version}")
        print("Please restart the application to use the new version.")
        raise SystemExit(0)

    if answer == "s":
        config["skipped_version"] = remote_version
        save_json_config(config_path, config_data)
        return

    if answer == "d":
        config["enabled"] = False
        save_json_config(config_path, config_data)
        return

    config["last_prompted_version"] = remote_version
    config["last_prompted_at"] = current_local_iso8601()
    save_json_config(config_path, config_data)


MANIFEST_FIELD_COUNT = 7
MANIFEST_PRINTF = r"%P\0%y\0%s\0%T@\0%m\0%u\0%g\0"
PATH_MANIFEST_PRINTF = r"%p\0%y\0%s\0%T@\0%m\0%u\0%g\0"


def parse_manifest_output(output: bytes) -> dict[str, EntryMeta]:
    entry_by_rel_path: dict[str, EntryMeta] = {}
    if not output:
        return entry_by_rel_path

    fields = output.split(b"\0")
    if fields and fields[-1] == b"":
        fields = fields[:-1]
    if len(fields) % MANIFEST_FIELD_COUNT != 0:
        raise ValueError(
            f"Invalid manifest field count: {len(fields)} is not divisible by {MANIFEST_FIELD_COUNT}"
        )

    for index in range(0, len(fields), MANIFEST_FIELD_COUNT):
        (
            rel_path_raw,
            entry_type_raw,
            size_raw,
            mtime_raw,
            perms_raw,
            owner_raw,
            group_raw,
        ) = fields[index : index + MANIFEST_FIELD_COUNT]
        rel_path_text = rel_path_raw.decode("utf-8")
        entry_type_text = entry_type_raw.decode("utf-8")
        entry_type = EntryType.DIRECTORY if entry_type_text == "d" else EntryType.FILE
        entry_by_rel_path[rel_path_text] = EntryMeta(
            rel_path=rel_path_text,
            entry_type=entry_type,
            size=int(size_raw.decode("utf-8")),
            mtime_s=int(float(mtime_raw.decode("utf-8"))),
            perms=int(perms_raw.decode("utf-8"), 8),
            owner=owner_raw.decode("utf-8"),
            group=group_raw.decode("utf-8"),
        )
    return entry_by_rel_path


def build_local_find_command(start_path: str, recursive: bool = False) -> list[str]:
    command = ["find", "-L", start_path, "-mindepth", "1"]
    if not recursive:
        command.extend(["-maxdepth", "1"])
    command.extend(["-printf", MANIFEST_PRINTF])
    return command


def build_remote_find_command(remote_root: str, start_path: str, recursive: bool = False) -> str:
    maxdepth = "" if recursive else " -maxdepth 1"
    return (
        f"cd {shlex.quote(remote_root)} && "
        f"find -L {shlex.quote(start_path)} -mindepth 1{maxdepth} "
        f"-printf {shlex.quote(MANIFEST_PRINTF)}"
    )


def build_local_tree_manifest_command(start_path: str) -> list[str]:
    return ["find", "-L", start_path, "-mindepth", "0", "-printf", PATH_MANIFEST_PRINTF]


def build_remote_tree_manifest_command(remote_root: str, start_path: str) -> str:
    return (
        f"cd {shlex.quote(remote_root)} && "
        f"find -L {shlex.quote(start_path)} -mindepth 0 "
        f"-printf {shlex.quote(PATH_MANIFEST_PRINTF)}"
    )


def list_local_entries(local_root: Path, rel_path: str) -> dict[str, EntryMeta]:
    start_path = rel_path if rel_path else "."
    output = subprocess.run(
        build_local_find_command(start_path),
        cwd=local_root,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    return parse_manifest_output(output)


def list_local_tree_entries(local_root: Path, rel_path: str) -> dict[str, EntryMeta]:
    output = subprocess.run(
        build_local_tree_manifest_command(rel_path),
        cwd=local_root,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    return parse_manifest_output(output)


def list_remote_side_entries(
    remote_target: str,
    remote_root: str,
    rel_path: str,
    ssh_opts: list[str],
    *,
    remote_is_local: bool,
) -> dict[str, EntryMeta]:
    if remote_is_local:
        return list_local_entries(Path(remote_root), rel_path)
    return list_remote_entries(remote_target, remote_root, rel_path, ssh_opts)


def list_remote_side_tree_entries(
    remote_target: str,
    remote_root: str,
    rel_path: str,
    ssh_opts: list[str],
    *,
    remote_is_local: bool,
) -> dict[str, EntryMeta]:
    if remote_is_local:
        return list_local_tree_entries(Path(remote_root), rel_path)
    return list_remote_tree_entries(remote_target, remote_root, rel_path, ssh_opts)


def list_remote_entries(
    remote_target: str,
    remote_root: str,
    rel_path: str,
    ssh_opts: list[str],
) -> dict[str, EntryMeta]:
    start_path = rel_path if rel_path else "."
    remote_command = build_remote_find_command(remote_root, start_path)
    output = subprocess.run(
        ["ssh", *ssh_opts, remote_target, remote_command],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    return parse_manifest_output(output)


def list_remote_tree_entries(
    remote_target: str,
    remote_root: str,
    rel_path: str,
    ssh_opts: list[str],
) -> dict[str, EntryMeta]:
    remote_command = build_remote_tree_manifest_command(remote_root, rel_path)
    output = subprocess.run(
        ["ssh", *ssh_opts, remote_target, remote_command],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    return parse_manifest_output(output)


def build_remote_permission_preflight_command(
    remote_root: str,
    rel_path: str,
    owner: str,
) -> str:
    return (
        "set -e; "
        f"cd {shlex.quote(remote_root)}; "
        f"find -L {shlex.quote(rel_path)} -mindepth 0 "
        f"! -user {shlex.quote(owner)} -print -quit"
    )


def build_remote_owner_preflight_command(
    remote_root: str,
    rel_path: str,
    owner: str,
) -> str:
    return build_remote_permission_preflight_command(remote_root, rel_path, owner)


def normalize_permission_mode(mode: str) -> str:
    mode = LEGACY_PERMISSION_MODE_MAP.get(mode, mode)
    if mode not in {"pvt:pvt", "grp:pvt", "grp:grp", "any:pvt", "any:grp", "any:any"}:
        raise ValueError(f"Invalid permission mode: {mode}")
    read_scope, write_scope = mode.split(":", 1)
    if PERMISSION_READ_ORDER.index(write_scope) > PERMISSION_READ_ORDER.index(read_scope):
        raise ValueError(f"Invalid permission mode: {mode}")
    return mode


def permission_chmod_modes(mode: str) -> tuple[str, str]:
    mode = normalize_permission_mode(mode)
    if mode == "pvt:pvt":
        return ("u+rwx,go-rwx,g-s", "u+rw,go-rwx")
    if mode == "grp:pvt":
        return ("u+rwx,g+rx,g-w,o-rwx,g+s", "u+rw,g+r,g-w,o-rwx")
    if mode == "grp:grp":
        return ("u+rwx,g+rwx,o-rwx,g+s", "u+rw,g+rw,o-rwx")
    if mode == "any:pvt":
        return ("u+rwx,g+rx,g-w,o+rx,o-w,g+s", "u+rw,g+r,g-w,o+r,o-w")
    if mode == "any:grp":
        return ("u+rwx,g+rwx,o+rx,o-w,g+s", "u+rw,g+rw,o+r,o-w")
    if mode == "any:any":
        return ("u+rwx,go+rwx,g+s", "u+rw,go+rw")
    raise ValueError(f"Invalid permission mode: {mode}")


def build_remote_permission_command(
    remote_root: str,
    rel_paths: list[str],
    mode: str,
    permission_group: str = "",
    *,
    owner: str = "",
) -> str:
    mode = normalize_permission_mode(mode)
    dir_mode, file_mode = permission_chmod_modes(mode)
    if not rel_paths:
        raise ValueError("No permission paths provided")

    quoted_paths = " ".join(shlex.quote(rel_path) for rel_path in rel_paths)
    quoted_owner = shlex.quote(owner) if owner else "$(id -un)"
    owner_filter = shlex.quote(owner) if owner else '"$owner"'
    commands = [
        "failed=0",
        f"owner={quoted_owner}",
        "owner_tmp=$(mktemp)",
        "owner_err=$(mktemp)",
        "cleanup() { rm -f \"$owner_tmp\" \"$owner_err\"; }",
        "trap 'cleanup; exit 130' INT TERM HUP",
        "trap cleanup EXIT",
        f"cd {shlex.quote(remote_root)} || exit 1",
        "echo '[1/3] Collecting skipped non-owned owners...'",
        (
            f"find -L {quoted_paths} ! -user {owner_filter} "
            "-printf '%u\\n' > \"$owner_tmp\" 2> \"$owner_err\" || true"
        ),
        "echo 'Skipped non-owned owners:'",
        (
            "if [ -s \"$owner_tmp\" ]; then "
            "sort \"$owner_tmp\" | uniq -c | sort -rn | "
            "while read -r count owner_name; do printf '  %-20s %s\\n' \"$owner_name\" \"$count\"; done; "
            "else echo '  (none)'; fi"
        ),
        (
            "if [ -s \"$owner_err\" ]; then "
            "echo 'Warnings:'; sed 's/^/  /' \"$owner_err\"; fi"
        ),
        "echo '[2/3] Applying selected group to owned entries...'",
    ]
    owner_filter = f"-user {shlex.quote(owner)}" if owner else '-user "$owner"'
    if permission_group:
        quoted_group = shlex.quote(permission_group)
        commands.append(
            f"find -L {quoted_paths} {owner_filter} ! -group {quoted_group} "
            f"-exec chgrp {quoted_group} {{}} + || failed=1"
        )
    else:
        commands.append("echo 'No selected group; skipping chgrp.'")
    commands.extend(
        [
            "echo '[3/3] Applying chmod to owned directories/files...'",
            (
                f"find -L {quoted_paths} {owner_filter} -type d "
                f"-exec chmod {shlex.quote(dir_mode)} {{}} + || failed=1"
            ),
            (
                f"find -L {quoted_paths} {owner_filter} -type f "
                f"-exec chmod {shlex.quote(file_mode)} {{}} + || failed=1"
            ),
            "echo 'Summary:'",
            "if [ \"$failed\" -eq 0 ]; then echo '  status: success'; else echo '  status: partial failed'; fi",
            f"echo '  mode: {mode}'",
            "exit \"$failed\"",
        ]
    )
    return "; ".join(commands)


def permission_mode_from_parts(read_scope: str, write_scope: str) -> str:
    return normalize_permission_mode(f"{read_scope}:{write_scope}")


def permission_result_lines(mode: str, permission_group: str = "") -> list[str]:
    mode = normalize_permission_mode(mode)
    dir_mode, file_mode = permission_chmod_modes(mode)
    lines = [f"result: {permission_mode_label(mode)}"]
    if permission_group:
        lines.append(f"  chgrp: {permission_group}")
    lines.append(f"  dirs:  {dir_mode}")
    lines.append(f"  files: {file_mode}")
    return lines


def permission_mode_label(mode: str) -> str:
    mode = normalize_permission_mode(mode)
    if mode == "pvt:pvt":
        return "[pvt:-]"
    if mode == "grp:pvt":
        return "[grp:r]"
    if mode == "grp:grp":
        return "[grp:w]"
    if mode == "any:pvt":
        return "[any:r]"
    if mode == "any:grp":
        return "[any:g]"
    if mode == "any:any":
        return "[any:w]"
    raise ValueError(f"Invalid permission mode: {mode}")


def parse_skipped_owner_line(line: str) -> tuple[str, int] | None:
    stripped = line.strip()
    if not stripped or stripped == "(none)":
        return None
    owner, sep, count_text = stripped.rpartition(" ")
    owner = owner.strip()
    if not sep or not owner:
        return None
    try:
        count = int(count_text)
    except ValueError:
        return None
    return owner, count


def format_skipped_owner_summary(owner_counts: dict[str, int]) -> str:
    if not owner_counts:
        return ""
    parts = [
        f"{owner}={count}"
        for owner, count in sorted(owner_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return "Skipped non-owned: " + ", ".join(parts) + "."


def join_rel_path(parent_rel_path: str, child_name: str) -> str:
    if not parent_rel_path:
        return child_name
    return f"{parent_rel_path}/{child_name}"


def sorted_children(node: TreeNode) -> list[TreeNode]:
    """Sort children by sync relevance.

    Priority:
    1. Items on both sides.
    2. Single-side items by modification time, newest first.
    3. Directories before files as a tie-breaker.
    """
    if node.sorted_children_cache is not None:
        return node.sorted_children_cache

    def sort_key(child_node: TreeNode) -> tuple[int, int, int, str]:
        left_exists = node_exists_on_left(child_node)
        right_exists = node_exists_on_right(child_node)
        dir_key = 0 if node_is_directory(child_node) else 1

        if left_exists and right_exists:
            return (0, dir_key, 0, child_node.name)

        if left_exists and child_node.left_entry:
            mtime_key = -child_node.left_entry.mtime_s
        elif right_exists and child_node.right_entry:
            mtime_key = -child_node.right_entry.mtime_s
        else:
            mtime_key = 0

        return (1, mtime_key, dir_key, child_node.name)

    node.sorted_children_cache = sorted(node.children.values(), key=sort_key)
    return node.sorted_children_cache


def node_has_children(node: TreeNode) -> bool:
    return bool(node.children)


def node_is_directory(node: TreeNode) -> bool:
    if node_has_children(node):
        return True
    if node.left_entry and node.left_entry.entry_type == EntryType.DIRECTORY:
        return True
    if node.right_entry and node.right_entry.entry_type == EntryType.DIRECTORY:
        return True
    return False


def node_exists_on_left(node: TreeNode) -> bool:
    return node.left_entry is not None


def node_exists_on_right(node: TreeNode) -> bool:
    return node.right_entry is not None


def node_has_load_error(node: TreeNode) -> bool:
    if node.left_load_error or node.right_load_error:
        return True
    return any(node_has_load_error(child_node) for child_node in node.children.values())


def node_has_self_difference(node: TreeNode) -> bool:
    if node.left_load_error or node.right_load_error:
        return True
    if node.left_entry is None or node.right_entry is None:
        return node.left_entry is not None or node.right_entry is not None

    if node.left_entry.entry_type != node.right_entry.entry_type:
        return True

    if node.left_entry.entry_type == EntryType.FILE:
        if node.left_entry.size != node.right_entry.size:
            return True  # different size → definitely different content
        if node.content_verified_same:
            return False  # hash-confirmed identical; metadata diff is irrelevant
        return node.left_entry.mtime_s != node.right_entry.mtime_s

    return False


def node_has_difference(node: TreeNode) -> bool:
    if node.has_difference_cache is None:
        if node_has_self_difference(node):
            node.has_difference_cache = True
        elif not node.children_loaded:
            node.has_difference_cache = False
        elif node.children_status_unchecked:
            node.has_difference_cache = False
        else:
            node.has_difference_cache = any(
                node_has_difference(child_node) for child_node in node.children.values()
            )
    return node.has_difference_cache


def node_is_confirmed_same(node: TreeNode) -> bool:
    """True only when both sides exist and every descendant has been loaded with no diff.

    A directory with unexplored subdirectories returns False (shown as white),
    even if no difference has been detected yet.
    """
    if node.confirmed_same_cache is None:
        if node.left_entry is None or node.right_entry is None:
            node.confirmed_same_cache = False
        elif node_has_self_difference(node):
            node.confirmed_same_cache = False
        elif node_is_directory(node):
            if not node.children_loaded or node.children_status_unchecked:
                node.confirmed_same_cache = False
            else:
                node.confirmed_same_cache = all(
                    node_is_confirmed_same(child) for child in node.children.values()
                )
        else:
            node.confirmed_same_cache = True
    return node.confirmed_same_cache


def selection_state(node: TreeNode) -> SelectionState:
    if node.selection_state_cache is not None:
        return node.selection_state_cache

    if not node_is_directory(node):
        node.selection_state_cache = (
            SelectionState.SELECTED if node.is_selected else SelectionState.UNSELECTED
        )
        return node.selection_state_cache

    if node.is_selected and not node.children_loaded:
        node.selection_state_cache = SelectionState.SELECTED
        return node.selection_state_cache

    if not node.children:
        node.selection_state_cache = (
            SelectionState.SELECTED if node.is_selected else SelectionState.UNSELECTED
        )
        return node.selection_state_cache

    child_states = [selection_state(child_node) for child_node in node.children.values()]
    if all(child_state == SelectionState.SELECTED for child_state in child_states):
        node.selection_state_cache = SelectionState.SELECTED
        return node.selection_state_cache
    if all(child_state == SelectionState.UNSELECTED for child_state in child_states):
        if node.is_selected:
            node.selection_state_cache = SelectionState.PARTIAL
        else:
            node.selection_state_cache = SelectionState.UNSELECTED
        return node.selection_state_cache
    node.selection_state_cache = SelectionState.PARTIAL
    return node.selection_state_cache


def set_subtree_selection(node: TreeNode, is_selected: bool) -> None:
    node.is_selected = is_selected
    clear_node_caches(node)
    for child_node in node.children.values():
        set_subtree_selection(child_node, is_selected)


def clear_node_caches(node: TreeNode, *, include_sorted: bool = False) -> None:
    if include_sorted:
        node.sorted_children_cache = None
    node.has_difference_cache = None
    node.confirmed_same_cache = None
    node.selection_state_cache = None


def clear_ancestor_caches(node: TreeNode | None, *, include_self: bool = True) -> None:
    current_node = node if include_self else node.parent if node is not None else None
    while current_node is not None:
        clear_node_caches(current_node)
        current_node = current_node.parent


def collect_selected_paths(node: TreeNode, source_side: str) -> list[str]:
    selected_rel_paths: list[str] = []
    if node.is_selected and node_has_load_error(node):
        return selected_rel_paths
    source_entry = node.left_entry if source_side == "left" else node.right_entry
    if node.rel_path and node.is_selected and source_entry is not None:
        if not node_is_directory(node) or selection_state(node) == SelectionState.SELECTED:
            selected_rel_paths.append(node.rel_path)
            return selected_rel_paths
    for child_node in sorted_children(node):
        selected_rel_paths.extend(collect_selected_paths(child_node, source_side))
    return selected_rel_paths


def collect_selected_node_paths(node: TreeNode) -> set[str]:
    selected_node_paths: set[str] = set()
    if node.is_selected:
        selected_node_paths.add(node.rel_path)
    for child_node in node.children.values():
        selected_node_paths.update(collect_selected_node_paths(child_node))
    return selected_node_paths


def deselect_all_nodes(node: TreeNode) -> int:
    """Recursively clear is_selected on every node. Returns the count of nodes cleared."""
    cleared = 0
    if node.is_selected:
        node.is_selected = False
        cleared += 1
    clear_node_caches(node)
    for child in node.children.values():
        cleared += deselect_all_nodes(child)
    return cleared


def collect_selected_nodes(node: TreeNode) -> list[TreeNode]:
    """Collect all selected TreeNode objects (not just paths)."""
    result: list[TreeNode] = []
    if node.rel_path and node.is_selected:
        result.append(node)
        return result  # don't descend into selected node — subtree will be handled
    for child_node in sorted_children(node):
        result.extend(collect_selected_nodes(child_node))
    return result


def collect_expanded_node_paths(node: TreeNode) -> set[str]:
    expanded_node_paths: set[str] = set()
    if node.is_expanded:
        expanded_node_paths.add(node.rel_path)
    for child_node in node.children.values():
        expanded_node_paths.update(collect_expanded_node_paths(child_node))
    return expanded_node_paths


def visible_nodes(
    root_node: TreeNode, pagination_size: int = DEFAULT_PAGINATION_SIZE
) -> list[TreeNode]:
    """Collect visible nodes with pagination support.

    When a directory has more than pagination_size children,
    only shows pagination_size items, followed by a "... N more" placeholder.
    """
    nodes: list[TreeNode] = []

    def make_more_placeholder(parent: TreeNode, remaining: int) -> TreeNode:
        """Create a placeholder node for '... N more'."""
        placeholder = TreeNode(
            name=f"... {remaining} more",
            rel_path=f"{parent.rel_path}/__more_placeholder__",
            parent=parent,
        )
        return placeholder

    def append_visible_nodes(node: TreeNode) -> None:
        if node.rel_path:
            nodes.append(node)
        if node.is_expanded:
            sorted_children_list = sorted_children(node)
            total_children = len(sorted_children_list)

            # Only apply pagination if children exceed threshold
            if total_children <= pagination_size:
                # Small directory: show all children
                for child_node in sorted_children_list:
                    append_visible_nodes(child_node)
            else:
                # Large directory: show first batch + placeholder
                shown = node.children_shown_count
                if shown == 0 or shown < pagination_size:
                    # Initialize with first batch
                    shown = pagination_size
                    node.children_shown_count = shown

                # Show the first `shown` children (from loaded list)
                for i, child_node in enumerate(sorted_children_list):
                    if i < shown:
                        append_visible_nodes(child_node)
                    else:
                        break

                # Add placeholder if there are more (using accurate total)
                remaining = total_children - shown
                if remaining > 0:
                    nodes.append(make_more_placeholder(node, remaining))

    append_visible_nodes(root_node)
    return nodes


def is_more_placeholder(node: TreeNode) -> bool:
    """Check if a node is a '... N more' placeholder."""
    return node.rel_path.endswith("/__more_placeholder__")


# ------------------------------------------------------------------------ #
#                                tui helpers                                #
# ------------------------------------------------------------------------ #


_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def truncate_text(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text.ljust(width)
    if width <= 3:
        return text[:width]
    return f"{text[: width - 3]}..."


def path_suffix_for_side(node: TreeNode, side: str) -> str:
    entry = node.left_entry if side == "left" else node.right_entry
    if entry is None:
        return ""
    if entry.entry_type == EntryType.DIRECTORY or node_has_children(node):
        return "/"
    return ""


def _fixed_permission_label(value: str) -> str:
    text = value[:5]
    pad = 5 - len(text)
    left = pad // 2
    right = pad - left
    if len(text) == 4:
        left = 0
        right = 1
    inner = (" " * left) + text + (" " * right)
    return f"[{inner}]"


def _mode_label(perms: int) -> str:
    mode = perms & 0o7777
    text = f"{mode:o}" if mode > 0o777 else f"{mode & 0o777:03o}"
    return _fixed_permission_label(text)


def remote_permission_badge(entry: EntryMeta) -> str:
    """Return a short access badge for remote files and directories."""
    mode = entry.perms & 0o777
    special = entry.perms & 0o7000
    if entry.entry_type == EntryType.DIRECTORY and special not in (0, 0o2000):
        return _mode_label(entry.perms)

    if entry.entry_type == EntryType.DIRECTORY:
        if mode == 0o700:
            return "[pvt:-]"
        if mode == 0o750:
            return "[grp:r]"
        if mode == 0o770:
            return "[grp:w]"
        if mode == 0o755:
            return "[any:r]"
        if mode == 0o775:
            return "[any:g]"
        if mode == 0o777:
            return "[any:w]"
    else:
        if special:
            return _mode_label(entry.perms)
        if mode == 0o600:
            return "[pvt:-]"
        if mode == 0o640:
            return "[grp:r]"
        if mode == 0o660:
            return "[grp:w]"
        if mode == 0o644:
            return "[any:r]"
        if mode == 0o664:
            return "[any:g]"
        if mode == 0o666:
            return "[any:w]"
    return _mode_label(entry.perms)


def remote_permission_label(entry: EntryMeta | None, view: str) -> str:
    if entry is None:
        return "[     ]"
    if view == "badge":
        return remote_permission_badge(entry)
    if view == "owner":
        return _fixed_permission_label(entry.owner) if entry.owner else "[     ]"
    if view == "group":
        return _fixed_permission_label(entry.group) if entry.group else "[     ]"
    if view == "mode":
        return _mode_label(entry.perms)
    raise ValueError(f"Invalid permission view: {view}")


def badge_color_pair(entry: EntryMeta | None) -> int:
    if entry is None:
        return 0
    badge = remote_permission_badge(entry)
    if badge == "[pvt:-]":
        return 6
    if badge.startswith("[grp:"):
        return 5
    if badge.startswith("[any:"):
        return 4
    return 9


def permission_view_color_pair(view: str, entry: EntryMeta | None) -> int:
    if entry is None:
        return 0
    if view == "badge":
        return badge_color_pair(entry)
    if view == "owner":
        return 4
    if view == "group":
        return 5
    if view == "mode":
        return 9
    return 0


def permission_badge_color_segments(label: str) -> list[tuple[str, int, bool]]:
    if label == "[pvt:-]":
        return [(label, 6, True)]
    if label in {"[grp:r]", "[grp:w]", "[any:r]", "[any:g]", "[any:w]"}:
        scope = label[1:4]
        write = label[5]
        scope_pair = 5 if scope == "grp" else 4
        if write == "r":
            write_pair = 8
        elif write == "g":
            write_pair = 5
        else:
            write_pair = 1
        return [
            ("[", 0, False),
            (scope, scope_pair, False),
            (":", 0, False),
            (write, write_pair, False),
            ("]", 0, False),
        ]
    return [(label, 9, False)]


_TREE_MID   = "├─ "
_TREE_LAST  = "└─ "
_TREE_CONT  = "│  "
_TREE_BLANK = "   "


def compute_tree_prefixes(visible: list[TreeNode]) -> list[str]:
    """Return the box-drawing prefix string for each visible node."""
    prefixes: list[str] = []
    for i, node in enumerate(visible):
        if node.depth <= 0:
            prefixes.append("")
            continue
        parts: list[str] = []
        for d in range(1, node.depth + 1):
            has_more = False
            for j in range(i + 1, len(visible)):
                vj = visible[j].depth
                if vj < d:
                    break
                if vj == d:
                    has_more = True
                    break
            if d < node.depth:
                parts.append(_TREE_CONT if has_more else _TREE_BLANK)
            else:
                parts.append(_TREE_MID if has_more else _TREE_LAST)
        prefixes.append("".join(parts))
    return prefixes


def render_side_cell(
    node: TreeNode,
    side: str,
    width: int,
    tree_prefix: str = "",
) -> str:
    # Special handling for "... more" placeholder
    if is_more_placeholder(node):
        expand_icon = "▶"
        cell_text = f"{tree_prefix}{expand_icon} {node.name}"
        return truncate_text(cell_text, width)

    entry = node.left_entry if side == "left" else node.right_entry
    load_error = node.left_load_error if side == "left" else node.right_load_error
    expand_icon = (
        "▼" if (node_is_expandable(node) and node.is_expanded)
        else "▶" if node_is_expandable(node)
        else " "
    )
    node_name = node.name if entry is not None else "<error>" if load_error else ""
    suffix = path_suffix_for_side(node, side)
    cell_text = f"{tree_prefix}{expand_icon} {node_name}{suffix}"
    return truncate_text(cell_text, width)


def selection_marker(node: TreeNode) -> str:
    return f"[{selection_state(node).value}]"


def format_local_root(local_root: Path) -> str:
    return f"{local_root.as_posix().rstrip('/')}/"


def format_remote_root(
    remote_target: str,
    remote_root: str,
    *,
    remote_is_local: bool = False,
) -> str:
    if remote_is_local:
        return f"{Path(remote_root).as_posix().rstrip('/')}/"
    return f"{remote_target}:{remote_root.rstrip('/')}/"


def build_rsync_command(
    file_list_path: Path,
    source_root: str,
    dest_root: str,
    ssh_cmd: str,
    use_checksum: bool,
    backup: bool = False,
    whole_file: bool = False,
) -> list[str]:
    command = [
        "rsync",
        "-av",
        "--no-perms",
        "--no-owner",
        "--no-group",
        "--omit-dir-times",
        "--keep-dirlinks",      # -K: treat symlinked dirs on dest as real dirs
        "--itemize-changes",
        "--progress",
        "--partial",
        "--partial-dir=.rsync-partial",
        "--from0",
        f"--files-from={file_list_path}",
        source_root,
        dest_root,
    ]
    if ssh_cmd:
        from0_index = command.index("--from0")
        command[from0_index:from0_index] = ["-e", ssh_cmd]
    if use_checksum:
        command.insert(2, "--checksum")
    if backup:
        command.insert(2, "--backup")
    if whole_file:
        command.insert(2, "--whole-file")
    return command


def node_is_expandable(node: TreeNode) -> bool:
    return node_is_directory(node) and (not node.children_loaded or bool(node.children))


def mouse_has_button(bstate: int, *names: str) -> bool:
    return any(bool(bstate & getattr(curses, name, 0)) for name in names)


def mouse_is_primary_click(bstate: int) -> bool:
    return mouse_has_button(
        bstate,
        "BUTTON1_CLICKED",
        "BUTTON1_PRESSED",
        "BUTTON1_DOUBLE_CLICKED",
    )


def mouse_event_mask() -> int:
    mask = 0
    for name in (
        "BUTTON1_CLICKED",
        "BUTTON1_PRESSED",
        "BUTTON1_DOUBLE_CLICKED",
        "BUTTON4_PRESSED",
        "BUTTON5_PRESSED",
    ):
        mask |= getattr(curses, name, 0)
    return mask or curses.ALL_MOUSE_EVENTS


# ------------------------------------------------------------------------ #
#                                  tree node                                #
# ------------------------------------------------------------------------ #


@dataclass(slots=True)
class TreeNode:
    name: str
    rel_path: str
    parent: TreeNode | None = None
    left_entry: EntryMeta | None = None
    right_entry: EntryMeta | None = None
    left_load_error: str = ""
    right_load_error: str = ""
    children: dict[str, TreeNode] = field(default_factory=dict)
    children_loaded: bool = False
    children_status_unchecked: bool = False
    is_expanded: bool = False
    is_selected: bool = False
    content_verified_same: bool = (
        False  # True = hash-confirmed identical despite metadata diff
    )
    children_shown_count: int = 0  # how many children are currently shown (pagination)
    total_children_count: int = -1  # total children count, -1 means unknown
    sorted_children_cache: list[TreeNode] | None = field(default=None, repr=False)
    has_difference_cache: bool | None = field(default=None, repr=False)
    confirmed_same_cache: bool | None = field(default=None, repr=False)
    selection_state_cache: SelectionState | None = field(default=None, repr=False)

    @property
    def depth(self) -> int:
        if self.parent is None:
            return -1
        return self.parent.depth + 1


# ------------------------------------------------------------------------ #
#                                  sync app                                 #
# ------------------------------------------------------------------------ #


class SyncApp:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.local_root = config.local_root.resolve()
        self.remote_spec = config.remote_spec
        self.remote_is_local = config.remote_is_local
        if self.remote_is_local:
            self.remote_target = ""
            self.remote_root = str(Path(config.remote_spec).resolve())
        else:
            self.remote_target, self.remote_root = split_remote_spec(config.remote_spec)

        # SSH ControlMaster: PID-scoped socket so concurrent instances do not
        # share a socket — if they did, the first instance to exit would send
        # "ssh -O exit" and break the remaining instances.
        host_slug = hashlib.sha1(self.remote_target.encode("utf-8")).hexdigest()[:12]
        self._ssh_socket_path: str = "" if self.remote_is_local else str(
            Path(tempfile.gettempdir()) / f"{APP_NAME}_{host_slug}_{os.getpid()}.sock"
        )
        self._control_master_closed: bool = False
        if not self.remote_is_local:
            atexit.register(self._close_control_master)

        # Remote identity (queried once; first SSH call establishes the master)
        self.remote_user: str = ""
        self.remote_groups: set[str] = set()
        self._query_remote_identity()

        self.root_node = TreeNode(name="", rel_path="")
        self.node_by_rel_path: dict[str, TreeNode] = {"": self.root_node}
        self.cursor_index = 0
        self.scroll_offset = 0
        self.message = "Loading manifests..."
        self.pending_action: str | None = None
        self.pending_permission: PermissionRequest | None = None
        self.pending_remote_edit_upload: RemoteEditUploadRequest | None = None
        self.pending_permission_any_write_confirmed = False
        self.pending_check_ignore_metadata = True
        self.pending_check_stop_depth_text = ""
        self.last_cursor_rel_path = ""
        self.initial_connection_ok = False
        self.list_layout: ListLayout | None = None
        self.footer_shortcut_hits: list[FooterShortcutHit] = []
        self.last_wheel_direction: int | None = None
        self.last_wheel_at: float = 0.0
        self.pagination_size = config.pagination_size
        self.diff_viewers = config.diff_viewers
        self.file_editor = config.file_editor
        self.image_opener = config.image_opener
        self.mouse_wheel = config.mouse_wheel
        self.permission_group = config.permission_group
        self.permission_group_source = config.permission_group_source
        self.permission_view = "badge"
        self._interrupt_requested: bool = False

        self.refresh_manifests(initial_load=True)
        self.initial_connection_ok = not self.root_node.left_load_error and not self.root_node.right_load_error

    def _visible_nodes(self) -> list[TreeNode]:
        """Get visible nodes with pagination support."""
        return visible_nodes(
            self.root_node,
            getattr(self, "pagination_size", DEFAULT_PAGINATION_SIZE),
        )

    # ------------------------------- SSH helpers ---------------------------- #

    def _ssh_opts(self) -> list[str]:
        """SSH options injected into every ssh/rsync call for ControlMaster reuse.

        Only ControlMaster options are overridden; all other settings (identity
        file, host key checking, port, user, etc.) are left to the user's
        ~/.ssh/config so colleagues can use their own SSH configuration.
        """
        if self._remote_is_local():
            return []
        return [
            "-o", f"ControlPath={self._ssh_socket_path}",
            "-o", "ControlMaster=auto",
            "-o", "ControlPersist=60",
        ]

    def _ssh_command(self) -> str:
        if self._remote_is_local():
            return ""
        return "ssh " + " ".join(shlex.quote(option) for option in self._ssh_opts())

    def _remote_is_local(self) -> bool:
        return bool(getattr(self, "remote_is_local", False))

    def _close_control_master(self) -> None:
        if self._remote_is_local():
            return
        if self._control_master_closed:
            return
        self._control_master_closed = True
        subprocess.run(
            ["ssh", *self._ssh_opts(), "-O", "exit", self.remote_target],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        Path(self._ssh_socket_path).unlink(missing_ok=True)

    def _query_remote_identity(self) -> None:
        """Query remote user name and groups once.

        Owner/group of each entry is now embedded in EntryMeta (via find %u/%g),
        so only the SSH user's own identity is needed here for comparison.
        """
        if self._remote_is_local():
            self.remote_user = pwd.getpwuid(os.geteuid()).pw_name
            groups: set[str] = set()
            for gid in set(os.getgroups()) | {os.getegid()}:
                try:
                    groups.add(grp.getgrgid(gid).gr_name)
                except KeyError:
                    continue
            self.remote_groups = groups
            return
        result = subprocess.run(
            ["ssh", *self._ssh_opts(), self.remote_target, "id -un && id -Gn"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if result.returncode != 0:
            return
        id_out = result.stdout.strip().splitlines()
        if len(id_out) < 2:
            return
        self.remote_user = id_out[0].strip()
        self.remote_groups = set(id_out[1].strip().split())

    # ------------------------------- permission helpers --------------------- #

    def _remote_effective_write(self, entry: EntryMeta) -> bool:
        """Return True if the SSH user has write permission on this remote entry."""
        p = entry.perms
        # If identity query failed, we don't know the user's role — allow upload
        # and let the remote filesystem reject unauthorized writes.
        if not self.remote_user:
            return bool(p & 0o222)  # any write bit set → probably writable by someone
        is_owner = self.remote_user == entry.owner
        in_group = bool(entry.group and entry.group in self.remote_groups)
        if is_owner and bool(p & 0o200):
            return True
        if in_group and bool(p & 0o020):
            return True
        return bool(p & 0o002)

    def _remote_path_writable(self, rel_path: str) -> bool:
        """Walk up the tree to find the nearest ancestor with a right_entry and check write."""
        node = self.node_by_rel_path.get(rel_path)
        while node is not None:
            if node.right_entry is not None:
                return self._remote_effective_write(node.right_entry)
            node = node.parent
        # No remote entry found — assume writable (owner case or new upload)
        return True

    def _selected_remote_permission_paths(self) -> list[str]:
        return sorted(collect_selected_paths(self.root_node, "right"))

    def _first_remote_non_owner_path(self, rel_paths: list[str]) -> str | None:
        if not self.remote_user:
            return "(remote user unknown)"
        for rel_path in rel_paths:
            remote_command = build_remote_permission_preflight_command(
                self.remote_root,
                rel_path,
                self.remote_user,
            )
            command = (
                ["bash", "-lc", remote_command]
                if self._remote_is_local()
                else ["ssh", *self._ssh_opts(), self.remote_target, remote_command]
            )
            result, interrupted = self._run_interruptible_subprocess(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if interrupted:
                raise PermissionActionInterrupted()
            if result.returncode != 0:
                err = result.stderr.strip() or f"owner preflight failed for {rel_path}"
                return err.splitlines()[0]
            first_path = result.stdout.strip().splitlines()
            if first_path:
                return first_path[0]
        return None

    def _permission_group_display(self) -> str:
        if self.permission_group:
            return f"{self.permission_group} ({self.permission_group_source})"
        return "<none>"

    def _permission_group_display_attr(self) -> int:
        if self.permission_group:
            return curses.color_pair(5)
        return curses.color_pair(3)

    def _disabled_text_attr(self) -> int:
        return curses.color_pair(6) | curses.A_DIM

    # ------------------------------- content verification ------------------- #

    def _collect_content_check_candidates(self, node: TreeNode) -> list[TreeNode]:
        """Walk subtree and return file nodes with same size but different mtime, not yet verified."""
        result: list[TreeNode] = []
        if (
            not node_is_directory(node)
            and node.left_entry is not None
            and node.right_entry is not None
            and node.left_entry.size == node.right_entry.size
            and node.left_entry.mtime_s != node.right_entry.mtime_s
            and not node.content_verified_same
        ):
            result.append(node)
        for child in node.children.values():
            result.extend(self._collect_content_check_candidates(child))
        return result

    def _rsync_content_check(self, candidates: list[TreeNode]) -> int:
        """Run rsync --checksum (dry-run) on candidates; mark byte-identical files as verified.

        Uses --no-perms/--no-owner/--no-group/--omit-dir-times so that only content
        differences count.  rsync itemize output format: 'YXcstpogaz path'
          Y = '.' → no content update needed (same)
          Y = '>' or '<' → content differs
        Returns the number of nodes confirmed identical.
        """
        if not candidates:
            return 0

        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            for node in candidates:
                f.write(node.rel_path.encode("utf-8"))
                f.write(b"\0")
            tmp_path = Path(f.name)

        self.message = f"rsync --checksum: comparing {len(candidates)} same-size files..."
        self.render()
        try:
            ssh_cmd = self._ssh_command()
            command = [
                "rsync",
                "-aniv",              # archive dry-run itemizes mtime-only checksum matches
                "--checksum",         # compare by content checksum, not mtime
                "--no-perms",
                "--no-owner",
                "--no-group",
                "--omit-dir-times",
                "--from0",
                f"--files-from={tmp_path}",
                format_local_root(self.local_root),
                format_remote_root(
                    self.remote_target,
                    self.remote_root,
                    remote_is_local=self._remote_is_local(),
                ),
            ]
            if ssh_cmd:
                from0_index = command.index("--from0")
                command[from0_index:from0_index] = ["-e", ssh_cmd]
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

        # Parse itemize lines: 11-char code + space + path
        # Y (first char) = '.' → same content; '>' / '<' / 'c' → needs update
        same_paths: set[str] = set()
        diff_paths: set[str] = set()
        for line in result.stdout.splitlines():
            if len(line) < 13 or line[11] != " " or line[1] != "f":
                continue  # skip non-file itemize lines (dirs, headers, stats)
            update_type = line[0]
            rel_path = line[12:]
            if update_type == ".":
                same_paths.add(rel_path)
            elif update_type in (">", "<", "c"):
                diff_paths.add(rel_path)

        matched = 0
        for node in candidates:
            if node.rel_path in same_paths:
                node.content_verified_same = True
                clear_ancestor_caches(node)
                matched += 1
            elif node.rel_path in diff_paths:
                node.content_verified_same = False
                clear_ancestor_caches(node)
        return matched

    # ------------------------------- lifecycle ------------------------------ #

    def refresh_manifests(self, initial_load: bool = False) -> None:
        selected_node_paths = collect_selected_node_paths(self.root_node)
        expanded_node_paths = collect_expanded_node_paths(self.root_node)
        if initial_load:
            selected_node_paths = set()
            expanded_node_paths = {""}

        self.initialize_tree()

        materialized_paths = sorted(
            (selected_node_paths | expanded_node_paths) - {""},
            key=lambda rel_path: (rel_path.count("/"), rel_path),
        )
        for rel_path in materialized_paths:
            node = self.ensure_path_loaded(rel_path)
            if node is not None and rel_path in selected_node_paths:
                node.is_selected = True
            if node is not None and rel_path in expanded_node_paths and node_is_directory(node):
                self.load_children(node)
                node.is_expanded = True

        visible = self._visible_nodes()
        if not visible:
            self.cursor_index = 0
            self.scroll_offset = 0
            self.message = "No entries found on either side."
            return

        if self.last_cursor_rel_path in self.node_by_rel_path:
            self.cursor_index = max(
                0,
                next(
                    (
                        index
                        for index, node in enumerate(visible)
                        if node.rel_path == self.last_cursor_rel_path
                    ),
                    0,
                ),
            )
        else:
            self.cursor_index = min(self.cursor_index, len(visible) - 1)
        self.ensure_cursor_visible()
        self.message = f"Loaded {len(self.root_node.children)} root entries."

    def _refresh_file_manifest_side(self, rel_path: str, side: str) -> bool:
        node = self.node_by_rel_path.get(rel_path)
        if node is None:
            return False

        try:
            if side == "left":
                entry_by_path = list_local_tree_entries(self.local_root, rel_path)
                new_entry = entry_by_path.get(rel_path)
                if new_entry != node.left_entry:
                    node.content_verified_same = False
                    clear_node_caches(node, include_sorted=True)
                node.left_entry = new_entry
                node.left_load_error = ""
            elif side == "right":
                entry_by_path = list_remote_side_tree_entries(
                    self.remote_target,
                    self.remote_root,
                    rel_path,
                    self._ssh_opts(),
                    remote_is_local=self._remote_is_local(),
                )
                new_entry = entry_by_path.get(rel_path)
                if new_entry != node.right_entry:
                    node.content_verified_same = False
                    clear_node_caches(node, include_sorted=True)
                node.right_entry = new_entry
                node.right_load_error = ""
            else:
                raise ValueError(f"Invalid manifest side: {side}")
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            if side == "left":
                node.left_load_error = str(exc)
            else:
                node.right_load_error = str(exc)
            self.message = f"Error refreshing {side} {rel_path}: {exc}"
            clear_ancestor_caches(node)
            return False

        if not node_is_directory(node):
            node.children_loaded = True
            node.children = {}
        clear_ancestor_caches(node)
        return True

    def initialize_tree(self) -> None:
        self.root_node = TreeNode(name="", rel_path="", is_expanded=True)
        self.node_by_rel_path = {"": self.root_node}
        self.load_children(self.root_node)

    def ensure_path_loaded(self, rel_path: str) -> TreeNode | None:
        current_node = self.root_node
        if not rel_path:
            return current_node

        for part in rel_path.split("/"):
            if not current_node.children_loaded:
                self.load_children(current_node)
            next_node = current_node.children.get(part)
            if next_node is None:
                return None
            current_node = next_node
        return current_node

    def load_children(self, node: TreeNode, limited: bool = True) -> None:
        """Load children of a directory node.

        Args:
            node: The directory node to load.
            limited: If True, use pagination for large directories.
                     If False, load all children (used for check operations).
        """
        if node.children_loaded or not node_is_directory(node) and node.rel_path:
            return

        # Check for interrupt
        if self._interrupt_requested:
            node.left_load_error = "Interrupted"
            node.right_load_error = "Interrupted"
            return

        # Determine which sides exist
        left_exists = node.left_entry is not None or not node.rel_path  # root always exists
        right_exists = node.right_entry is not None or not node.rel_path

        self.message = f"Loading {node.rel_path or '/'} ..."
        if hasattr(self, "stdscr"):
            self.render()

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_local = pool.submit(
                self.list_local_child_entries, node
            ) if left_exists else pool.submit(lambda: {})
            f_remote = pool.submit(
                self.list_remote_child_entries, node
            ) if right_exists else pool.submit(lambda: {})

            spin_i = 0
            pending = {f_local, f_remote}
            while pending:
                if self._interrupt_requested:
                    pool.shutdown(wait=False)
                    node.left_load_error = "Interrupted"
                    node.right_load_error = "Interrupted"
                    return
                done, pending = concurrent.futures.wait(pending, timeout=0.1)
                if pending and hasattr(self, "stdscr"):
                    self.message = (
                        f"Loading {node.rel_path or '/'} "
                        f"{_SPINNER[spin_i % len(_SPINNER)]}"
                    )
                    self.render()
                    spin_i += 1

            try:
                left_entry_by_name = f_local.result()
                node.left_load_error = ""
            except (OSError, subprocess.CalledProcessError, ValueError) as exc:
                left_entry_by_name = {}
                node.left_load_error = str(exc)
                self.message = f"Error listing local {node.rel_path or '/'}: {exc}"
            try:
                right_entry_by_name = f_remote.result()
                node.right_load_error = ""
            except (OSError, subprocess.CalledProcessError, ValueError) as exc:
                right_entry_by_name = {}
                node.right_load_error = str(exc)
                self.message = f"Error listing remote {node.rel_path or '/'}: {exc}"

        # Build children nodes
        existing_children = node.children
        node.children = {}
        child_names = sorted(set(left_entry_by_name.keys()) | set(right_entry_by_name.keys()))
        total_count = len(child_names)
        node.total_children_count = total_count
        if limited and total_count > self.pagination_size:
            node.children_shown_count = self.pagination_size
        else:
            node.children_shown_count = total_count
        inherit_selection = node.is_selected

        for child_name in child_names:
            child_rel_path = join_rel_path(node.rel_path, child_name)
            child_node = existing_children.get(child_name)
            if child_node is None:
                child_node = self.node_by_rel_path.get(child_rel_path)
            if child_node is None:
                child_node = TreeNode(
                    name=child_name,
                    rel_path=child_rel_path,
                    parent=node,
                    is_selected=inherit_selection,
                )
                self.node_by_rel_path[child_rel_path] = child_node
            child_node.parent = node
            new_left = left_entry_by_name.get(child_name)
            new_right = right_entry_by_name.get(child_name)
            if new_left != child_node.left_entry or new_right != child_node.right_entry:
                child_node.content_verified_same = False
                clear_node_caches(child_node, include_sorted=True)
            child_node.left_entry = new_left
            child_node.right_entry = new_right
            child_node.children_status_unchecked = False
            if not node_is_directory(child_node):
                child_node.children_loaded = True
                child_node.children = {}
            node.children[child_name] = child_node

        node.children_loaded = True
        node.children_status_unchecked = bool(limited and total_count > self.pagination_size)
        clear_node_caches(node, include_sorted=True)
        clear_ancestor_caches(node.parent)

    def load_more_children(self, node: TreeNode) -> None:
        """Reveal the next page of already-loaded children."""
        if self._interrupt_requested:
            return

        current_shown = node.children_shown_count
        total_count = len(node.children)
        node.total_children_count = total_count
        node.children_shown_count = min(current_shown + self.pagination_size, total_count)
        remaining = total_count - node.children_shown_count
        if remaining > 0:
            self.message = f"Showing {node.children_shown_count} items, {remaining} more."
        else:
            self.message = f"All {total_count} items shown."

    def list_local_child_entries(self, node: TreeNode) -> dict[str, EntryMeta]:
        if node.rel_path and node.left_entry is None:
            return {}
        return list_local_entries(self.local_root, node.rel_path)

    def list_remote_child_entries(self, node: TreeNode) -> dict[str, EntryMeta]:
        if node.rel_path and node.right_entry is None:
            return {}
        return list_remote_side_entries(
            self.remote_target,
            self.remote_root,
            node.rel_path,
            self._ssh_opts(),
            remote_is_local=self._remote_is_local(),
        )

    def run(self) -> None:
        curses.wrapper(self._run)

    def _run(self, stdscr: curses.window) -> None:
        self.stdscr = stdscr
        self._interrupt_requested = False

        # Set up SIGINT handler to interrupt operations without exiting TUI
        original_sigint = signal.signal(signal.SIGINT, self._handle_sigint)

        curses.curs_set(0)
        stdscr.keypad(True)
        configure_escape_delay()
        curses.mousemask(mouse_event_mask())
        curses.mouseinterval(180)
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_RED, -1)  # both sides, different
        curses.init_pair(2, curses.COLOR_BLUE, -1)  # status line
        curses.init_pair(3, curses.COLOR_YELLOW, -1)  # help text / local-only
        curses.init_pair(4, curses.COLOR_CYAN, -1)  # remote-only
        curses.init_pair(5, curses.COLOR_GREEN,  -1)   # both exist, confirmed same
        dim_text_color = (
            DIM_TEXT_COLOR_256
            if getattr(curses, "COLORS", 0) > DIM_TEXT_COLOR_256
            else curses.COLOR_WHITE
        )
        curses.init_pair(6, dim_text_color, -1)  # dimmed gray
        curses.init_pair(7, curses.COLOR_GREEN, -1)  # reserved permission green
        curses.init_pair(8, curses.COLOR_YELLOW, -1)  # readonly / warning
        curses.init_pair(9, curses.COLOR_MAGENTA, -1)  # numeric permission

        try:
            while True:
                self.render()
                # Check for interrupt after render
                if self._interrupt_requested:
                    self._interrupt_requested = False
                    self.message = "Operation interrupted."
                    continue
                key = stdscr.getch()
                if key == ord("q"):
                    return
                self.handle_key(key)
        finally:
            # Restore original SIGINT handler
            signal.signal(signal.SIGINT, original_sigint)
            self._close_control_master()

    def _handle_sigint(self, signum: int, frame) -> None:
        """Handle Ctrl+C by setting interrupt flag instead of exiting."""
        self._interrupt_requested = True

    # ------------------------------- rendering ------------------------------ #

    def render(self) -> None:
        stdscr = self.stdscr
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        if height < MIN_MAIN_RENDER_HEIGHT or width < MIN_MAIN_RENDER_WIDTH:
            self._render_too_small_warning(height, width)
            return

        header_left = f"Local:  {self.local_root}"
        header_right = f"Remote: {self.remote_spec}"
        stdscr.addnstr(0, 0, header_left, width - 1, curses.A_BOLD)
        stdscr.addnstr(1, 0, header_right, width - 1, curses.A_BOLD)

        if height >= 5 and width > 1:
            stdscr.addnstr(
                height - 4,
                0,
                "─" * (width - 1),
                width - 1,
                curses.color_pair(2),
            )
        self._render_footer_shortcuts(height - 3, width)

        # Color legend — each segment rendered in its actual color
        _legend = [
            ("unexplored", curses.A_NORMAL),
            (" local-only", curses.color_pair(3)),
            (" remote-only", curses.color_pair(4)),
            (" same", curses.color_pair(5)),
            (" diff", curses.color_pair(1)),
        ]
        _lx = 0  # min(len(nav_help), width - 1)
        for _label, _attr in _legend:
            if _lx + len(_label) >= width - 1:
                break
            stdscr.addnstr(height - 2, _lx, _label, width - 1 - _lx, _attr)
            _lx += len(_label)

        status_text = self.message
        if self.pending_action is not None:
            if self.pending_action == "check":
                ignore_metadata = getattr(self, "pending_check_ignore_metadata", True)
                depth_text = getattr(self, "pending_check_stop_depth_text", "")
                depth_display = depth_text if depth_text else "_"
                status_text = (
                    "Check selected. "
                    f"[m] ignore metadata: {'on' if ignore_metadata else 'off'}  "
                    f"[depth: {depth_display}]  [y] run  [n] cancel  [?] help"
                )
            elif self.pending_action == "clear":
                status_text = "Clear ALL selections? Press y to confirm, n to cancel."
            elif self.pending_action == "permission" and self.pending_permission is not None:
                if (
                    normalize_permission_mode(self.pending_permission.mode) == "any:any"
                    and getattr(self, "pending_permission_any_write_confirmed", False)
                ):
                    status_text = (
                        "Other writable is dangerous. Press y again to execute, n to cancel."
                    )
                else:
                    status_text = (
                        f"Apply permission {self.pending_permission.mode} to "
                        f"{len(self.pending_permission.rel_paths)} remote entries. "
                        "Press y to confirm, n to cancel."
                    )
            elif (
                self.pending_action == "remote_edit_upload"
                and self.pending_remote_edit_upload is not None
            ):
                status_text = (
                    f"Upload edited remote file {self.pending_remote_edit_upload.rel_path}? "
                    "Press y to confirm, n to cancel."
                )
            else:
                status_text = (
                    f"{self.pending_action} selected entries. Press y to confirm, n to cancel."
                )
        stdscr.addnstr(height - 1, 0, status_text, width - 1, curses.color_pair(2))

        visible = self._visible_nodes()
        if not visible:
            stdscr.refresh()
            return

        row_start = 3
        row_end = height - 4
        list_height = max(row_end - row_start, 1)
        self.ensure_cursor_visible(list_height=list_height, visible=visible)

        selection_width = 4
        badge_width = 7
        divider_width = badge_width
        panel_width = max((width - selection_width - badge_width) // 2, 10)
        self.list_layout = ListLayout(
            row_start=row_start,
            list_height=list_height,
            selection_width=selection_width,
            panel_width=panel_width,
            divider_width=divider_width,
            badge_width=badge_width,
        )

        # Column header labels (row 2)
        col_header = (
            " " * selection_width
            + "LOCAL".ljust(panel_width)
            + "PERM".center(badge_width)
            + "REMOTE".ljust(panel_width)
        )
        stdscr.addnstr(2, 0, col_header, width - 1, curses.A_BOLD | curses.A_UNDERLINE)

        tree_prefixes = compute_tree_prefixes(visible)

        for list_row in range(list_height):
            visible_index = self.scroll_offset + list_row
            if visible_index >= len(visible):
                break

            screen_row = row_start + list_row
            node = visible[visible_index]
            is_cursor_row = visible_index == self.cursor_index

            # Special handling for "... more" placeholder
            if is_more_placeholder(node):
                row_color = 0  # white/default
                row_attr = (curses.A_REVERSE if is_cursor_row else curses.A_DIM) | row_color
                stdscr.addnstr(screen_row, 0, "    ", selection_width, row_attr)
                self._addnstr_clipped(
                    screen_row,
                    selection_width,
                    render_side_cell(node, "left", panel_width, tree_prefix=tree_prefixes[visible_index]),
                    panel_width,
                    row_attr,
                    width,
                )
                self._addnstr_clipped(
                    screen_row,
                    selection_width + panel_width,
                    " " * badge_width,
                    badge_width,
                    curses.A_DIM,
                    width,
                )
                self._addnstr_clipped(
                    screen_row,
                    selection_width + panel_width + badge_width,
                    render_side_cell(node, "right", panel_width, tree_prefix=tree_prefixes[visible_index]),
                    panel_width,
                    row_attr,
                    width,
                )
                continue

            left_exists = node_exists_on_left(node)
            right_exists = node_exists_on_right(node)
            if left_exists and right_exists:
                if node_has_difference(node):
                    row_color = curses.color_pair(1)   # red — different
                elif node_is_confirmed_same(node):
                    row_color = curses.color_pair(5)   # green — all descendants confirmed same
                else:
                    row_color = 0                       # white — both exist, not fully explored
            elif left_exists:
                row_color = curses.color_pair(3)   # yellow — local only
            else:
                row_color = curses.color_pair(4)  # cyan   — remote only
            row_attr = (curses.A_REVERSE if is_cursor_row else curses.A_NORMAL) | row_color

            marker_text = selection_marker(node)
            marker_attr = row_attr
            if selection_state(node) != SelectionState.UNSELECTED:
                marker_attr |= curses.A_BOLD
            self._addnstr_clipped(screen_row, 0, marker_text, selection_width, marker_attr, width)

            left_attr = row_attr | (curses.A_BOLD if left_exists else 0)
            self._addnstr_clipped(
                screen_row,
                selection_width,
                render_side_cell(node, "left", panel_width, tree_prefix=tree_prefixes[visible_index]),
                panel_width,
                left_attr,
                width,
            )

            badge_text = ""
            badge_attr = row_attr
            badge_segments: list[tuple[str, int, bool]] | None = None
            if node.right_entry is not None:
                view = getattr(self, "permission_view", "badge")
                badge_text = remote_permission_label(node.right_entry, view)
                if view == "badge":
                    badge_segments = permission_badge_color_segments(badge_text)
                else:
                    badge_attr = curses.color_pair(permission_view_color_pair(view, node.right_entry))
                    if is_cursor_row:
                        badge_attr |= curses.A_REVERSE
            badge_x = selection_width + panel_width
            if badge_segments is not None:
                segment_x = badge_x
                for segment_text, pair, dim in badge_segments:
                    segment_attr = curses.color_pair(pair) if pair else row_attr
                    if dim:
                        segment_attr |= curses.A_DIM
                    if is_cursor_row:
                        segment_attr |= curses.A_REVERSE
                    self._addnstr_clipped(
                        screen_row,
                        segment_x,
                        segment_text,
                        max(badge_width - (segment_x - badge_x), 0),
                        segment_attr,
                        width,
                    )
                    segment_x += len(segment_text)
            else:
                self._addnstr_clipped(
                    screen_row,
                    badge_x,
                    badge_text,
                    badge_width,
                    badge_attr,
                    width,
                )

            right_attr = row_attr | (curses.A_BOLD if right_exists else 0)
            self._addnstr_clipped(
                screen_row,
                selection_width + panel_width + badge_width,
                render_side_cell(node, "right", panel_width, tree_prefix=tree_prefixes[visible_index]),
                panel_width,
                right_attr,
                width,
            )

        stdscr.refresh()

    def _render_too_small_warning(self, height: int, width: int) -> None:
        self.footer_shortcut_hits = []
        if height <= 0 or width <= 1:
            self.stdscr.refresh()
            return

        warning_attr = curses.color_pair(8) | curses.A_BOLD
        lines = [
            "Window too small",
            f"Need {MIN_MAIN_RENDER_WIDTH}x{MIN_MAIN_RENDER_HEIGHT}+",
            "Resize terminal",
        ]
        if height < 5 or width < 20:
            self._addnstr_clipped(0, 0, "Resize terminal", width - 1, warning_attr, width)
            self.stdscr.refresh()
            return

        content_width = max(len(line) for line in lines)
        box_width = min(max(content_width + 4, 20), width - 1)
        box_height = min(len(lines) + 2, height)
        top = max((height - box_height) // 2, 0)
        left = max((width - box_width) // 2, 0)

        border = "+" + "-" * max(box_width - 2, 0) + "+"
        self._addnstr_clipped(top, left, border, box_width, warning_attr, width)
        for index, line in enumerate(lines[: max(box_height - 2, 0)]):
            row = top + 1 + index
            padded = line.center(max(box_width - 4, 0))
            self._addnstr_clipped(row, left, f"| {padded} |", box_width, warning_attr, width)
        if box_height >= 2:
            self._addnstr_clipped(
                top + box_height - 1,
                left,
                border,
                box_width,
                warning_attr,
                width,
            )
        self.stdscr.refresh()

    def _addnstr_clipped(
        self,
        y: int,
        x: int,
        text: str,
        max_chars: int,
        attr: int,
        screen_width: int,
    ) -> None:
        right_edge = screen_width - 1
        if x < 0 or x >= right_edge or max_chars <= 0:
            return
        clipped_chars = min(max_chars, right_edge - x)
        if clipped_chars <= 0:
            return
        self.stdscr.addnstr(y, x, text, clipped_chars, attr)

    def _render_footer_shortcuts(self, y: int, width: int) -> None:
        nav_shortcuts = [
            ("Up/Down", "move", None),
            ("Left/Right", "fold", None),
            ("Space", "toggle", ord(" ")),
        ]
        action_shortcuts = [
            ("d", "download", ord("d")),
            ("u", "upload", ord("u")),
            ("f/F", "diff", ord("f")),
            ("o/O", "open", ord("o")),
            ("p/P", "permission", ord("p")),
            ("c", "check", ord("c")),
            ("x", "clear", ord("x")),
            ("r", "refresh", ord("r")),
            ("?", "helper", ord("?")),
            ("q", "quit", None),
        ]
        self.footer_shortcut_hits = []
        if y < 0 or width <= 1:
            return

        max_x = width - 1
        shortcuts = self._fit_footer_shortcuts(nav_shortcuts + action_shortcuts, max_x)
        if len(shortcuts) < 3:
            shortcuts = self._fit_footer_shortcuts(action_shortcuts, max_x)

        x = 0
        for key_text, label, trigger_key in shortcuts:
            if x >= max_x:
                break
            key_start = x
            x = self._add_footer_text(y, x, key_text, max_x, curses.color_pair(3))
            if x >= max_x:
                break
            x = self._add_footer_text(y, x, f"={label}", max_x, curses.A_NORMAL)
            key_end = x
            if trigger_key is not None and key_end > key_start:
                if key_text == "p/P":
                    self.footer_shortcut_hits.extend(
                        [
                            FooterShortcutHit(y=y, start_x=key_start, end_x=key_start + 1, key=ord("p")),
                            FooterShortcutHit(y=y, start_x=key_start + 2, end_x=key_start + 3, key=ord("P")),
                        ]
                    )
                else:
                    self.footer_shortcut_hits.append(
                        FooterShortcutHit(
                            y=y,
                            start_x=key_start,
                            end_x=key_end,
                            key=trigger_key,
                        )
                    )
            if x >= max_x:
                break
            x = self._add_footer_text(y, x, " ", max_x, curses.A_NORMAL)

    def _fit_footer_shortcuts(
        self,
        shortcuts: list[tuple[str, str, int | None]],
        max_width: int,
    ) -> list[tuple[str, str, int | None]]:
        fitted = list(shortcuts)
        while fitted and self._footer_shortcuts_width(fitted) > max_width:
            removable_index = 0
            if fitted[0][0] == "?":
                removable_index = 1
            if removable_index >= len(fitted):
                break
            fitted.pop(removable_index)
        if not any(key_text == "?" for key_text, _label, _trigger in fitted):
            helper = next((item for item in shortcuts if item[0] == "?"), None)
            if helper is not None:
                fitted.append(helper)
                while len(fitted) > 1 and self._footer_shortcuts_width(fitted) > max_width:
                    removable_index = 0 if fitted[0][0] != "?" else 1
                    if removable_index >= len(fitted):
                        break
                    fitted.pop(removable_index)
        return fitted

    def _footer_shortcuts_width(self, shortcuts: list[tuple[str, str, int | None]]) -> int:
        return sum(len(key_text) + 1 + len(label) for key_text, label, _trigger in shortcuts) + max(
            len(shortcuts) - 1,
            0,
        )

    def _add_footer_text(self, y: int, x: int, text: str, max_x: int, attr: int) -> int:
        remaining = max_x - x
        if remaining <= 0:
            return x
        self.stdscr.addnstr(y, x, text, remaining, attr)
        return x + min(len(text), remaining)

    # ------------------------------- navigation ----------------------------- #

    def ensure_cursor_visible(
        self,
        list_height: int | None = None,
        visible: list[TreeNode] | None = None,
    ) -> None:
        if visible is None:
            visible = self._visible_nodes()
        if not visible:
            self.cursor_index = 0
            self.scroll_offset = 0
            return

        self.cursor_index = max(0, min(self.cursor_index, len(visible) - 1))
        self.last_cursor_rel_path = visible[self.cursor_index].rel_path

        if list_height is None:
            height, _ = self.stdscr.getmaxyx() if hasattr(self, "stdscr") else (24, 120)
            list_height = max(height - 7, 1)

        max_scroll = max(len(visible) - list_height, 0)
        self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))
        if self.cursor_index < self.scroll_offset:
            self.scroll_offset = self.cursor_index
        elif self.cursor_index >= self.scroll_offset + list_height:
            self.scroll_offset = self.cursor_index - list_height + 1

    def move_cursor_by(self, delta: int) -> None:
        visible = self._visible_nodes()
        if not visible:
            return
        self.cursor_index = max(0, min(self.cursor_index + delta, len(visible) - 1))
        self.ensure_cursor_visible(visible=visible)

    def current_node(self) -> TreeNode | None:
        visible = self._visible_nodes()
        if not visible:
            return None
        return visible[self.cursor_index]

    def toggle_current_node(self) -> None:
        node = self.current_node()
        if node is None:
            return
        next_selected = selection_state(node) == SelectionState.UNSELECTED
        set_subtree_selection(node, next_selected)
        clear_ancestor_caches(node.parent)
        selected_count = len(collect_selected_node_paths(self.root_node))
        self.message = f"Updated selection. Marked nodes: {selected_count}."

    def collapse_or_move_to_parent(self) -> None:
        node = self.current_node()
        if node is None:
            return
        if node_is_directory(node) and node.is_expanded:
            node.is_expanded = False
            self.message = f"Collapsed {node.rel_path or '/'}."
            return
        if node.parent is None or node.parent.rel_path == "":
            return

        parent_rel_path = node.parent.rel_path
        visible = self._visible_nodes()
        self.cursor_index = next(
            index for index, visible_node in enumerate(visible) if visible_node.rel_path == parent_rel_path
        )
        self.ensure_cursor_visible()

    def expand_or_move_to_child(self) -> None:
        node = self.current_node()
        if node is None:
            return

        # Handle "... more" placeholder - actually load more children
        if is_more_placeholder(node):
            parent = node.parent
            if parent is not None:
                self.load_more_children(parent)
                return

        if not node_is_directory(node):
            return
        if not node.children_loaded:
            self.message = f"Loading {node.rel_path or '/'} ..."
            self.render()
            self.load_children(node)
        if not node.is_expanded:
            node.is_expanded = True
            self.message = f"Expanded {node.rel_path or '/'}."
            return
        self.cursor_index = min(self.cursor_index + 1, len(self._visible_nodes()) - 1)
        self.ensure_cursor_visible()

    def toggle_expand_current_directory(self) -> None:
        node = self.current_node()
        if node is None or not node_is_directory(node):
            return
        if node.is_expanded:
            node.is_expanded = False
            self.message = f"Collapsed {node.rel_path or '/'}."
            return
        if not node.children_loaded:
            self.message = f"Loading {node.rel_path or '/'} ..."
            self.render()
            self.load_children(node)
        node.is_expanded = True
        self.message = f"Expanded {node.rel_path or '/'}."

    def footer_shortcut_key_at(self, x: int, y: int) -> int | None:
        for hit in getattr(self, "footer_shortcut_hits", []):
            if hit.contains(x, y):
                return hit.key
        return None

    def handle_mouse_event(self) -> None:
        _mouse_id, x, y, _z, bstate = curses.getmouse()
        if mouse_has_button(bstate, "BUTTON1_DOUBLE_CLICKED"):
            shortcut_key = self.footer_shortcut_key_at(x, y)
            if shortcut_key is not None:
                self.handle_key(shortcut_key)
                return

        if mouse_has_button(bstate, "BUTTON4_PRESSED"):
            self._handle_mouse_wheel(-1)
            return
        if mouse_has_button(bstate, "BUTTON5_PRESSED"):
            self._handle_mouse_wheel(1)
            return

        if not mouse_is_primary_click(bstate):
            return
        visible = self._visible_nodes()
        if not visible:
            return
        if self.list_layout is None:
            return
        visible_index = self.list_layout.visible_index_at(
            y,
            self.scroll_offset,
            len(visible),
        )
        if visible_index is None:
            return

        self.cursor_index = visible_index
        self.ensure_cursor_visible()

        # Check if clicked on "... more" placeholder
        node = visible[visible_index]
        if is_more_placeholder(node):
            self.expand_or_move_to_child()
            return

        if self.list_layout.is_selection_column(x):
            self.toggle_current_node()
            return
        if mouse_has_button(bstate, "BUTTON1_DOUBLE_CLICKED"):
            self.toggle_expand_current_directory()

    def _handle_mouse_wheel(self, direction: int) -> None:
        mouse_wheel = getattr(
            self,
            "mouse_wheel",
            MouseWheelConfig(
                step=DEFAULT_MOUSE_WHEEL_STEP,
                coalesce_ms=DEFAULT_MOUSE_WHEEL_COALESCE_MS,
            ),
        )
        coalesce_seconds = max(0, mouse_wheel.coalesce_ms) / 1000
        if coalesce_seconds > 0:
            now = time.monotonic()
            last_direction = getattr(self, "last_wheel_direction", None)
            last_at = getattr(self, "last_wheel_at", 0.0)
            self.last_wheel_direction = direction
            self.last_wheel_at = now
            if last_direction == direction and now - last_at < coalesce_seconds:
                return
        self.move_cursor_by(direction * max(1, mouse_wheel.step))

    # ------------------------------- sync logic ----------------------------- #

    def _load_subtree(self, node: TreeNode) -> None:
        """Recursively load all unloaded children of a node, updating the spinner."""
        if self._interrupt_requested:
            return
        if not node_is_directory(node):
            return
        if node.rel_path and (node.left_entry is None or node.right_entry is None):
            return
        if node.children_status_unchecked:
            node.children_status_unchecked = False
            clear_node_caches(node)
            clear_ancestor_caches(node.parent)
        if not node.children_loaded:
            self.message = f"Checking {node.rel_path or '/'} ..."
            self.render()
            self.load_children(node, limited=False)  # Unlimited for check operations
        for child in node.children.values():
            if self._interrupt_requested:
                return
            _load_subtree_node = child
            self._load_subtree(_load_subtree_node)

    def _can_check_descend(self, node: TreeNode) -> bool:
        if not node_is_directory(node):
            return False
        if node.rel_path and (node.left_entry is None or node.right_entry is None):
            return False
        if (
            node.left_entry is not None
            and node.right_entry is not None
            and node.left_entry.entry_type != node.right_entry.entry_type
        ):
            return False
        return True

    def _load_check_children(self, node: TreeNode) -> None:
        if self._interrupt_requested or not self._can_check_descend(node):
            return
        if node.children_status_unchecked:
            node.children_status_unchecked = False
            clear_node_caches(node)
            clear_ancestor_caches(node.parent)
        if not node.children_loaded:
            self.message = f"Checking {node.rel_path or '/'} ..."
            self.render()
            self.load_children(node, limited=False)

    def _load_check_tree_to_relative_depth(
        self, node: TreeNode, current_depth: int, max_depth: int
    ) -> None:
        if self._interrupt_requested or current_depth >= max_depth:
            return
        self._load_check_children(node)
        for child in sorted_children(node):
            self._load_check_tree_to_relative_depth(child, current_depth + 1, max_depth)

    def _nodes_at_relative_depth(
        self, node: TreeNode, current_depth: int, target_depth: int
    ) -> list[TreeNode]:
        if current_depth == target_depth:
            return [node]
        if not node.children_loaded:
            return []
        result: list[TreeNode] = []
        for child in sorted_children(node):
            result.extend(
                self._nodes_at_relative_depth(child, current_depth + 1, target_depth)
            )
        return result

    def _check_node_short_circuit_risk(
        self, node: TreeNode, *, ignore_metadata: bool
    ) -> bool:
        if node.left_load_error or node.right_load_error:
            return True
        if node.left_entry is None or node.right_entry is None:
            return node.right_entry is not None
        if node.left_entry.entry_type != node.right_entry.entry_type:
            return True
        if node.left_entry.entry_type != EntryType.FILE:
            return False
        if node.left_entry.size != node.right_entry.size:
            return True
        if node.left_entry.mtime_s == node.right_entry.mtime_s:
            return False
        if not ignore_metadata:
            return True
        return self._rsync_content_check([node]) != 1

    def _check_until_short_circuit_risk(
        self, node: TreeNode, *, ignore_metadata: bool
    ) -> bool:
        if self._interrupt_requested:
            return True
        if self._check_node_short_circuit_risk(node, ignore_metadata=ignore_metadata):
            return True
        self._load_check_children(node)
        for child in sorted_children(node):
            if self._check_until_short_circuit_risk(
                child, ignore_metadata=ignore_metadata
            ):
                return True
        return False

    def _execute_check_with_stop_depth(
        self, selected_nodes: list[TreeNode], stop_depth: int, *, ignore_metadata: bool
    ) -> None:
        for node in selected_nodes:
            self._load_check_tree_to_relative_depth(node, 0, stop_depth + 1)
        for node in selected_nodes:
            units = self._nodes_at_relative_depth(node, 0, stop_depth)
            if not units:
                units = [node]
            for unit in units:
                self._check_until_short_circuit_risk(
                    unit, ignore_metadata=ignore_metadata
                )

    def execute_check(self) -> None:
        """Recursively load all selected nodes to resolve white (unexplored) state."""
        selected_nodes = collect_selected_nodes(self.root_node)
        if not selected_nodes:
            self.pending_action = None
            self.message = "No entries selected for check."
            return
        self.pending_action = None  # clear first so render() shows message, not confirm prompt
        self.message = f"Checking {len(selected_nodes)} selected entries..."
        self.render()
        count = 0
        ignore_metadata = getattr(self, "pending_check_ignore_metadata", True)
        stop_depth_text = getattr(self, "pending_check_stop_depth_text", "")
        if stop_depth_text:
            self._execute_check_with_stop_depth(
                selected_nodes,
                int(stop_depth_text),
                ignore_metadata=ignore_metadata,
            )
            count = len(selected_nodes)
            self.message = (
                f"Check complete for {count} selected entries. "
                f"Stopped at depth {int(stop_depth_text)}."
            )
            return
        for node in selected_nodes:
            self._load_subtree(node)
            count += 1

        # rsync --checksum for files that share size but differ in mtime when
        # the check is allowed to ignore metadata-only differences.
        candidates: list[TreeNode] = []
        if ignore_metadata:
            for node in selected_nodes:
                candidates.extend(self._collect_content_check_candidates(node))
        matched = 0
        if candidates:
            matched = self._rsync_content_check(candidates)

        summary = f"Check complete for {count} selected entries."
        if candidates:
            summary += f" Content: {matched}/{len(candidates)} same-size files byte-identical."
        self.message = summary

    def start_action(self, action: str) -> None:
        if action in ("download", "upload") and (
            self.root_node.left_load_error or self.root_node.right_load_error
        ):
            self.message = "Cannot sync while root listing has errors. Press r to retry."
            self.pending_action = None
            return

        if action == "check":
            selected_nodes = collect_selected_nodes(self.root_node)
            if not selected_nodes:
                self.message = "No entries selected to check."
                return
            self.pending_check_ignore_metadata = True
            self.pending_check_stop_depth_text = ""
            self.pending_action = "check"
            return

        if action == "clear":
            selected_nodes = collect_selected_nodes(self.root_node)
            if not selected_nodes:
                self.message = "No selections to clear."
                return
            self.pending_action = "clear"
            return

        if action == "permission":
            selected_paths = self._selected_remote_permission_paths()
            if not selected_paths:
                self.message = "No selected remote entries for permission change."
                self.pending_action = None
                self.pending_permission = None
                return
            choice = self._choose_permission_mode(len(selected_paths))
            if choice is None:
                self.message = "Cancelled permission mode selection."
                self.pending_action = None
                self.pending_permission = None
                return
            mode, permission_group = choice
            self.pending_permission = PermissionRequest(
                mode=mode,
                rel_paths=selected_paths,
                permission_group=permission_group,
            )
            self.pending_permission_any_write_confirmed = False
            self.pending_action = "permission"
            self.message = (
                f"Apply permission {mode} to {len(selected_paths)} remote entries. "
                "Press y to confirm, n to cancel."
            )
            return

        source_side = "right" if action == "download" else "left"
        selected_paths = collect_selected_paths(self.root_node, source_side)

        if action == "upload":
            selected_paths = [
                p for p in selected_paths if self._remote_path_writable(p)
            ]
            if not selected_paths:
                self.message = "No writable remote paths in selection. Check [grp:w]/[any:g] dirs."
                self.pending_action = None
                return

        if not selected_paths:
            self.message = f"No selectable {source_side} entries are currently selected."
            self.pending_action = None
            return

        self.pending_action = action
        self.message = f"Prepared {action} for {len(selected_paths)} entries."

    def _expand_selected_paths(
        self, rel_paths: list[str], source_side: str
    ) -> tuple[list[str], dict[str, EntryMeta]]:
        """Expand directory paths into all contained paths so rsync transfers recursively.

        rsync --files-from does NOT recurse into directories even with -a/-r,
        so we must explicitly list all descendants.
        """
        entry_by_path: dict[str, EntryMeta] = {}
        for rel_path in rel_paths:
            if source_side == "left":
                entry_by_path.update(list_local_tree_entries(self.local_root, rel_path))
            else:
                entry_by_path.update(
                    list_remote_side_tree_entries(
                        self.remote_target,
                        self.remote_root,
                        rel_path,
                        self._ssh_opts(),
                        remote_is_local=self._remote_is_local(),
                    )
                )
        return sorted(entry_by_path.keys()), entry_by_path

    def _split_paths_by_checksum(
        self,
        selected_paths: list[str],
        entry_by_path: dict[str, EntryMeta],
    ) -> list[tuple[bool, list[str]]]:
        dirs: list[str] = []
        checksum_files: list[str] = []
        quick_files: list[str] = []
        for rel_path in selected_paths:
            entry = entry_by_path.get(rel_path)
            if entry is not None and entry.entry_type == EntryType.DIRECTORY:
                dirs.append(rel_path)
                continue
            size = entry.size if entry is not None else None
            if self.config.checksum_policy.should_checksum(rel_path, size):
                checksum_files.append(rel_path)
            else:
                quick_files.append(rel_path)

        groups: list[tuple[bool, list[str]]] = []
        if checksum_files:
            groups.append((True, sorted(set(dirs + checksum_files))))
        if quick_files or (dirs and not checksum_files):
            groups.append((False, sorted(set(dirs + quick_files))))
        return groups

    def execute_permission_request(self) -> None:
        request = self.pending_permission
        if request is None:
            self.pending_action = None
            self.message = "No pending permission request."
            return

        self.pending_action = None
        self.pending_permission = None
        self.pending_permission_any_write_confirmed = False
        self.message = (
            f"Applying permission {request.mode} to {len(request.rel_paths)} remote entries..."
        )
        self.render()
        remote_command = build_remote_permission_command(
            self.remote_root,
            request.rel_paths,
            request.mode,
            request.permission_group,
            owner=self.remote_user,
        )
        command = (
            ["bash", "-lc", remote_command]
            if self._remote_is_local()
            else ["ssh", *self._ssh_opts(), self.remote_target, remote_command]
        )
        self.suspend_tui()
        returncode = 1
        skipped_owner_counts: dict[str, int] = {}
        try:
            group_display = request.permission_group or "not change group"
            print(f"Running permission: {request.mode}")
            print(f"Remote: {self.remote_spec}")
            print(f"Targets: {len(request.rel_paths)} selected paths")
            print(f"Group: {group_display}")
            print()
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            in_skipped_owner_section = False
            if process.stdout is not None:
                for output_line in process.stdout:
                    print(output_line, end="")
                    line_text = output_line.rstrip("\n")
                    if line_text == "Skipped non-owned owners:":
                        in_skipped_owner_section = True
                        continue
                    if in_skipped_owner_section:
                        if not output_line.startswith("  "):
                            in_skipped_owner_section = False
                            continue
                        parsed_owner = parse_skipped_owner_line(output_line)
                        if parsed_owner is not None:
                            owner_name, owner_count = parsed_owner
                            skipped_owner_counts[owner_name] = (
                                skipped_owner_counts.get(owner_name, 0) + owner_count
                            )
            returncode = process.wait()
            if returncode == 0:
                input("Permission completed. Press Enter to return to the TUI...")
            elif returncode in (130, -signal.SIGINT):
                input("Permission interrupted. Press Enter to return to the TUI...")
            else:
                input("Permission completed with warnings. Press Enter to return to the TUI...")
        finally:
            self.resume_tui()

        skipped_summary = format_skipped_owner_summary(skipped_owner_counts)
        if returncode == 0:
            self.refresh_manifests(initial_load=False)
            self.message = "Permission completed and refreshed."
            if skipped_summary:
                self.message = f"{self.message} {skipped_summary}"
        elif returncode in (130, -signal.SIGINT):
            self._interrupt_requested = False
            self.message = "Permission interrupted. Press r to refresh."
            if skipped_summary:
                self.message = f"Permission interrupted. {skipped_summary} Press r to refresh."
        else:
            self.message = "Permission completed with warnings. Press r to refresh."
            if skipped_summary:
                self.message = (
                    f"Permission completed with warnings. {skipped_summary} Press r to refresh."
                )

    def _run_interruptible_subprocess(
        self,
        argv: list[str],
        **kwargs: object,
    ) -> tuple[subprocess.CompletedProcess[str], bool]:
        kwargs.setdefault("start_new_session", True)
        process = subprocess.Popen(argv, **kwargs)
        while True:
            if getattr(self, "_interrupt_requested", False):
                self._interrupt_requested = False
                self._terminate_interrupted_process(process)
                self._reap_interrupted_process(process)
                return (
                    subprocess.CompletedProcess(
                        argv,
                        process.returncode if process.returncode is not None else -signal.SIGTERM,
                        stdout="",
                        stderr="",
                    ),
                    True,
                )
            try:
                stdout, stderr = process.communicate(timeout=0.1)
                return (
                    subprocess.CompletedProcess(
                        argv,
                        process.returncode,
                        stdout=stdout,
                        stderr=stderr,
                    ),
                    False,
                )
            except subprocess.TimeoutExpired:
                if not getattr(self, "_interrupt_requested", False):
                    continue
                self._interrupt_requested = False
                self._terminate_interrupted_process(process)
                self._reap_interrupted_process(process)
                return (
                    subprocess.CompletedProcess(
                        argv,
                        process.returncode if process.returncode is not None else -signal.SIGTERM,
                        stdout="",
                        stderr="",
                    ),
                    True,
                )

    def _terminate_interrupted_process(self, process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (AttributeError, OSError, ProcessLookupError, TypeError):
            process.terminate()

    def _kill_interrupted_process(self, process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (AttributeError, OSError, ProcessLookupError, TypeError):
            process.kill()

    def _reap_interrupted_process(self, process: subprocess.Popen[str]) -> None:
        def reap() -> None:
            try:
                process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                self._kill_interrupted_process(process)
                try:
                    process.communicate()
                except Exception:
                    pass
            except Exception:
                pass

        threading.Thread(target=reap, daemon=True).start()

    def execute_pending_action(self) -> None:
        if self.pending_action is None:
            return

        if self.pending_action == "check":
            self.execute_check()
            return

        if self.pending_action == "clear":
            self.pending_action = None
            count = deselect_all_nodes(self.root_node)
            self.message = f"Cleared {count} selection(s)."
            return

        if self.pending_action == "permission":
            self.execute_permission_request()
            return

        if self.pending_action == "remote_edit_upload":
            self._execute_remote_edit_upload()
            return

        action = self.pending_action
        source_side = "right" if action == "download" else "left"
        selected_paths = sorted(collect_selected_paths(self.root_node, source_side))

        if action == "upload":
            selected_paths = [
                p for p in selected_paths if self._remote_path_writable(p)
            ]

        if not selected_paths:
            self.pending_action = None
            self.message = "Selection disappeared after refresh."
            return

        self.pending_action = None  # clear first so render() shows message, not confirm prompt
        self.message = f"Starting {action} for {len(selected_paths)} entries..."
        self.render()
        selected_paths, entry_by_path = self._expand_selected_paths(
            selected_paths,
            source_side,
        )
        sync_groups = self._split_paths_by_checksum(selected_paths, entry_by_path)
        if not sync_groups:
            self.message = "No source paths were found during recursive expansion."
            return

        source_root = (
            format_remote_root(
                self.remote_target,
                self.remote_root,
                remote_is_local=self._remote_is_local(),
            )
            if action == "download"
            else format_local_root(self.local_root)
        )
        dest_root = (
            format_local_root(self.local_root)
            if action == "download"
            else format_remote_root(
                self.remote_target,
                self.remote_root,
                remote_is_local=self._remote_is_local(),
            )
        )

        ssh_cmd = self._ssh_command()
        commands: list[tuple[Path, bool, list[str]]] = []
        for use_checksum, group_paths in sync_groups:
            with tempfile.NamedTemporaryFile("wb", delete=False) as file_list_file:
                for rel_path in group_paths:
                    file_list_file.write(rel_path.encode("utf-8"))
                    file_list_file.write(b"\0")
                file_list_path = Path(file_list_file.name)
            commands.append(
                (
                    file_list_path,
                    use_checksum,
                    build_rsync_command(
                        file_list_path,
                        source_root,
                        dest_root,
                        ssh_cmd,
                        use_checksum,
                        backup=action == "download",
                        whole_file=action == "download",
                    ),
                )
            )

        self.suspend_tui()
        sync_ok = False
        try:
            for _file_list_path, use_checksum, command in commands:
                mode = "checksum" if use_checksum else "size+mtime"
                print(f"Running {mode}: {' '.join(command)}")
                subprocess.run(command, check=True)
            input("Sync completed. Press Enter to return to the TUI...")
            sync_ok = True
        except subprocess.CalledProcessError as exc:
            input(
                f"Sync failed (rsync exit code {exc.returncode}). "
                "Press Enter to return to the TUI..."
            )
        finally:
            for file_list_path, _use_checksum, _command in commands:
                file_list_path.unlink(missing_ok=True)
            self.resume_tui()

        self.refresh_manifests(initial_load=False)
        if sync_ok:
            self.message = (
                f"Completed {source_side} -> "
                f"{'local' if action == 'download' else 'remote'} sync."
            )
        else:
            self.message = "Sync failed — check terminal output above for details."

    def suspend_tui(self) -> None:
        curses.def_prog_mode()
        curses.endwin()

    def resume_tui(self) -> None:
        curses.reset_prog_mode()
        self.stdscr.keypad(True)
        curses.curs_set(0)
        self.stdscr.clear()
        self.stdscr.refresh()

    # ------------------------------- popup overlay -------------------------- #

    def _text_cell_width(self, text: str) -> int:
        width = 0
        for char in text:
            if unicodedata.combining(char):
                continue
            width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
        return width

    def _sanitize_popup_text(self, text: str) -> str:
        expanded = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text.expandtabs(4))
        return "".join(
            " " if unicodedata.category(char)[0] == "C" else char
            for char in expanded
        )

    def _slice_popup_cells(self, text: str, start: int, width: int) -> str:
        if width <= 0:
            return ""
        sanitized = self._sanitize_popup_text(text)
        cells = 0
        used = 0
        result: list[str] = []
        for char in sanitized:
            char_width = 0 if unicodedata.combining(char) else (
                2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
            )
            next_cells = cells + char_width
            if next_cells <= start:
                cells = next_cells
                continue
            if cells < start:
                char = " "
                char_width = 1
            if used + char_width > width:
                break
            result.append(char)
            used += char_width
            cells = next_cells
        if used < width:
            result.append(" " * (width - used))
        return "".join(result)

    def _popup_add_cells(
        self,
        win: curses.window,
        y: int,
        x: int,
        text: str,
        width: int,
        attr: int = 0,
    ) -> None:
        if width <= 0:
            return
        safe_text = self._slice_popup_cells(text, 0, width)
        try:
            win.addnstr(y, x, safe_text, len(safe_text), attr)
        except curses.error:
            pass

    def _show_popup(self, title: str, lines: list[str]) -> None:
        """Scrollable centered overlay. Arrows scroll/pan, Esc closes.

        Lines starting with +/-/@ are colored as unified-diff output.
        """
        scroll = 0
        hscroll = 0
        while True:
            if getattr(self, "_interrupt_requested", False):
                self._interrupt_requested = False
            self.render()
            height, width = self.stdscr.getmaxyx()

            max_line_len = max((self._text_cell_width(self._sanitize_popup_text(l)) for l in lines), default=0)
            title_width = self._text_cell_width(self._sanitize_popup_text(title))
            content_w = min(max(max_line_len, title_width + 4, 24), max(width - 8, 10))
            box_w = content_w + 4
            inner_h = min(max(len(lines), 1), max(height - 8, 1))
            # rows: top-border + separator + content + footer + bottom-border
            box_h = inner_h + 4

            start_y = max((height - box_h) // 2, 0)
            start_x = max((width - box_w) // 2, 0)
            box_h = min(box_h, height - start_y)
            box_w = min(box_w, width - start_x)
            inner_h = max(box_h - 4, 1)
            content_w = max(box_w - 4, 1)
            hscroll = max(0, min(hscroll, max(max_line_len - content_w, 0)))

            win = curses.newwin(box_h, box_w, start_y, start_x)
            win.scrollok(False)
            win.erase()
            win.box()

            # Title in top border
            title_str = f" {title} "
            title_x = max((box_w - self._text_cell_width(title_str)) // 2, 1)
            self._popup_add_cells(win, 0, title_x, title_str, box_w - title_x - 1, curses.A_BOLD)

            # Separator under title
            self._popup_add_cells(win, 1, 1, "-" * (box_w - 2), box_w - 2)

            # Content lines with diff coloring
            for row, line in enumerate(lines[scroll : scroll + inner_h]):
                if line.startswith("+") and not line.startswith("+++"):
                    attr = curses.color_pair(5)  # green
                elif line.startswith("-") and not line.startswith("---"):
                    attr = curses.color_pair(1)  # red
                elif line.startswith("@"):
                    attr = curses.color_pair(2)  # cyan
                else:
                    attr = 0
                visible_line = self._slice_popup_cells(line, hscroll, content_w)
                self._popup_add_cells(win, 2 + row, 1, " " * (box_w - 2), box_w - 2)
                self._popup_add_cells(win, 2 + row, 2, visible_line, content_w, attr)

            # Footer is inside the border, not on top of it.
            footer_y = box_h - 2
            hint = " Esc:close  Up/Down:scroll  Left/Right:pan "
            self._popup_add_cells(win, footer_y, 1, " " * (box_w - 2), box_w - 2)
            self._popup_add_cells(win, footer_y, 1, hint, min(self._text_cell_width(hint), box_w - 2), curses.color_pair(3))
            status_parts = []
            if len(lines) > inner_h:
                status_parts.append(f"{scroll + 1}-{min(scroll + inner_h, len(lines))}/{len(lines)}")
            if max_line_len > content_w:
                status_parts.append(f"col {hscroll + 1}-{min(hscroll + content_w, max_line_len)}/{max_line_len}")
            if status_parts:
                pos = f" {'  '.join(status_parts)} "
                pos_width = self._text_cell_width(pos)
                pos_x = max(box_w - pos_width - 1, 1)
                if pos_x > min(self._text_cell_width(hint), box_w - 2) + 1:
                    self._popup_add_cells(win, footer_y, pos_x, pos, box_w - pos_x - 1, curses.color_pair(2))

            win.box()
            self._popup_add_cells(win, 0, title_x, title_str, box_w - title_x - 1, curses.A_BOLD)

            win.refresh()

            key = self.stdscr.getch()
            if key == 27:
                return
            elif key == curses.KEY_UP:
                scroll = max(0, scroll - 1)
            elif key == curses.KEY_DOWN:
                scroll = min(max(0, len(lines) - inner_h), scroll + 1)
            elif key == curses.KEY_LEFT:
                hscroll = max(0, hscroll - 8)
            elif key == curses.KEY_RIGHT:
                hscroll = min(max(0, max_line_len - content_w), hscroll + 8)
            elif key == curses.KEY_PPAGE:
                scroll = max(0, scroll - inner_h)
            elif key == curses.KEY_NPAGE:
                scroll = min(max(0, len(lines) - inner_h), scroll + inner_h)
            elif key == getattr(curses, "KEY_HOME", -1):
                hscroll = 0
            elif key == getattr(curses, "KEY_END", -1):
                hscroll = max(0, max_line_len - content_w)

    # ------------------------------- file editor ---------------------------- #

    def _file_opener_for_path(self, file_path: Path) -> FileEditor:
        if is_image_file_path(file_path):
            return getattr(self, "image_opener", self.file_editor)
        return self.file_editor

    def _run_file_editor(self, file_path: Path) -> FileEditor | None:
        opener = self._file_opener_for_path(file_path)
        try:
            command = build_file_editor_command(opener, file_path)
        except ValueError as exc:
            self.message = str(exc)
            return None

        if opener.wait:
            should_suspend = hasattr(self, "stdscr")
            if should_suspend:
                self.suspend_tui()
            try:
                result = subprocess.run(command)
            finally:
                if should_suspend:
                    self.resume_tui()
            if (
                result.returncode in (130, -signal.SIGINT)
                and not opener.can_modify
            ):
                self._interrupt_requested = False
                return opener
            if result.returncode != 0:
                self.message = f"Opener exited with status {result.returncode}."
                return None
            return opener

        try:
            subprocess.Popen(command)
        except OSError as exc:
            self.message = f"Failed to open file: {exc}"
            return None
        return opener

    def _try_open_local_file(self) -> None:
        node = self.current_node()
        if node is None:
            return
        if node_is_directory(node):
            self.message = "Open file is only available for files, not directories."
            return
        if not node_exists_on_left(node):
            self.message = "Local open requires the file to exist on the local side."
            return

        local_path = self.local_root / node.rel_path
        if not local_path.exists():
            self.message = f"Local file does not exist: {node.rel_path}"
            return

        opener = self._run_file_editor(local_path)
        if opener is not None:
            if opener.can_modify:
                if self._refresh_file_manifest_side(node.rel_path, "left"):
                    self.message = f"Opened local file {node.rel_path}."
            else:
                self.message = (
                    f"Opened local file {node.rel_path}; press r to refresh after external edits."
                )

    def _remote_file_path(self, rel_path: str) -> Path:
        return Path(self.remote_root) / rel_path

    def _fetch_remote_file_bytes(self, rel_path: str) -> bytes:
        if self._remote_is_local():
            return self._remote_file_path(rel_path).read_bytes()
        remote_path = f"{self.remote_root.rstrip('/')}/{rel_path}"
        fetch = subprocess.run(
            ["ssh", *self._ssh_opts(), self.remote_target, f"cat {shlex.quote(remote_path)}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return fetch.stdout

    def _try_open_remote_file(self) -> None:
        node = self.current_node()
        if node is None:
            return
        if node_is_directory(node):
            self.message = "Open remote file is only available for files, not directories."
            return
        if not node_exists_on_right(node):
            self.message = "Remote open requires the file to exist on the remote side."
            return

        self.message = f"Fetching remote {node.rel_path}..."
        if hasattr(self, "stdscr"):
            self.render()

        try:
            remote_bytes = self._fetch_remote_file_bytes(node.rel_path)
        except (OSError, subprocess.CalledProcessError) as exc:
            err = (
                exc.stderr.decode(errors="replace").strip()
                if isinstance(exc, subprocess.CalledProcessError) and exc.stderr
                else str(exc)
            )
            self.message = f"Failed to fetch remote file: {err or '(no output)'}"
            return

        temp_root = Path(tempfile.mkdtemp(prefix=f"{APP_NAME}-remote-edit-"))
        temp_path = temp_root / node.rel_path
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(remote_bytes)
        before_hash = hashlib.sha256(remote_bytes).hexdigest()

        opener = self._run_file_editor(temp_path)
        if opener is None:
            shutil.rmtree(temp_root, ignore_errors=True)
            return

        if not opener.can_modify:
            self.message = (
                f"Opened temporary remote copy {node.rel_path}; system opener cannot upload changes."
            )
            return

        after_hash = hashlib.sha256(temp_path.read_bytes()).hexdigest()
        if after_hash == before_hash:
            shutil.rmtree(temp_root, ignore_errors=True)
            self.message = f"Remote file {node.rel_path} closed without changes."
            return

        self.pending_remote_edit_upload = RemoteEditUploadRequest(
            rel_path=node.rel_path,
            temp_root=temp_root,
        )
        self.pending_action = "remote_edit_upload"
        self.message = (
            f"Upload edited remote file {node.rel_path}? Press y to confirm, n to cancel."
        )

    def _execute_remote_edit_upload(self) -> None:
        request = self.pending_remote_edit_upload
        self.pending_action = None
        self.pending_remote_edit_upload = None
        if request is None:
            self.message = "No pending remote edit upload."
            return
        try:
            if not self._remote_path_writable(request.rel_path):
                self.message = "Remote file is not writable; edited temporary copy was discarded."
                return
            if self._execute_upload_from_local_root([request.rel_path], request.temp_root):
                self._refresh_file_manifest_side(request.rel_path, "right")
                self.message = "Completed edited file upload."
        finally:
            shutil.rmtree(request.temp_root, ignore_errors=True)

    def _execute_upload_from_local_root(
        self,
        selected_paths: list[str],
        source_local_root: Path,
    ) -> bool:
        entry_by_path: dict[str, EntryMeta] = {}
        for rel_path in selected_paths:
            local_path = source_local_root / rel_path
            if not local_path.exists():
                continue
            stat = local_path.stat()
            entry_by_path[rel_path] = EntryMeta(
                rel_path=rel_path,
                entry_type=EntryType.DIRECTORY if local_path.is_dir() else EntryType.FILE,
                size=stat.st_size,
                mtime_s=int(stat.st_mtime),
                perms=stat.st_mode & 0o777,
            )

        upload_paths = sorted(entry_by_path)
        sync_groups = self._split_paths_by_checksum(upload_paths, entry_by_path)
        if not sync_groups:
            self.message = "No source paths were found during recursive expansion."
            return False

        ssh_cmd = self._ssh_command()
        commands: list[tuple[Path, bool, list[str]]] = []
        for use_checksum, group_paths in sync_groups:
            with tempfile.NamedTemporaryFile("wb", delete=False) as file_list_file:
                for rel_path in group_paths:
                    file_list_file.write(rel_path.encode("utf-8"))
                    file_list_file.write(b"\0")
                file_list_path = Path(file_list_file.name)
            commands.append(
                (
                    file_list_path,
                    use_checksum,
                    build_rsync_command(
                        file_list_path,
                        format_local_root(source_local_root),
                        format_remote_root(
                            self.remote_target,
                            self.remote_root,
                            remote_is_local=self._remote_is_local(),
                        ),
                        ssh_cmd,
                        use_checksum,
                    ),
                )
            )

        if hasattr(self, "stdscr"):
            self.suspend_tui()
        sync_ok = False
        try:
            for _file_list_path, use_checksum, command in commands:
                mode = "checksum" if use_checksum else "size+mtime"
                if hasattr(self, "stdscr"):
                    print(f"Running {mode}: {' '.join(command)}")
                subprocess.run(command, check=True)
            if hasattr(self, "stdscr"):
                input("Upload completed. Press Enter to return to the TUI...")
            sync_ok = True
        except subprocess.CalledProcessError as exc:
            if hasattr(self, "stdscr"):
                input(
                    f"Upload failed (rsync exit code {exc.returncode}). "
                    "Press Enter to return to the TUI..."
                )
        finally:
            for file_list_path, _use_checksum, _command in commands:
                file_list_path.unlink(missing_ok=True)
            if hasattr(self, "stdscr"):
                self.resume_tui()

        self.message = (
            "Completed edited file upload."
            if sync_ok
            else "Upload failed - check terminal output above for details."
        )
        return sync_ok

    def _choose_permission_mode(self, target_count: int) -> tuple[str, str] | None:
        read_index = 0
        write_scope = "pvt"
        use_selected_group = bool(self.permission_group)
        while True:
            if getattr(self, "_interrupt_requested", False):
                self._interrupt_requested = False
            read_scope = PERMISSION_READ_ORDER[read_index]
            if PERMISSION_READ_ORDER.index(write_scope) > read_index:
                write_scope = read_scope
            mode = permission_mode_from_parts(read_scope, write_scope)
            effective_group = self.permission_group if use_selected_group else ""
            group_value = (
                self.permission_group
                if self.permission_group and use_selected_group
                else "not change group"
            )
            lines = [
                "Remote permission",
                "",
                f"Targets: {target_count} selected remote entries",
                "",
                f"[r] read:   {read_scope}",
                f"[w] write:  {write_scope}",
                f"[g] group:  {group_value}",
                "",
                *permission_result_lines(mode, effective_group),
                "",
                "y: continue",
                "Esc: cancel",
            ]
            self.render()
            height, width = self.stdscr.getmaxyx()
            content_w = min(max((self._text_cell_width(line) for line in lines), default=0), 56)
            box_w = min(max(content_w + 4, 34), max(width - 8, 10))
            box_h = min(len(lines) + 4, max(height - 4, 5))
            start_y = max((height - box_h) // 2, 0)
            start_x = max((width - box_w) // 2, 0)
            win = curses.newwin(box_h, box_w, start_y, start_x)
            win.erase()
            win.box()
            title = " Permission "
            title_x = max((box_w - self._text_cell_width(title)) // 2, 1)
            self._popup_add_cells(win, 0, title_x, title, box_w - title_x - 1, curses.A_BOLD)
            disabled_attr = self._disabled_text_attr()
            for row, line in enumerate(lines[: max(box_h - 2, 0)]):
                if line.startswith("[w] write:"):
                    prefix = "[w] write:  "
                    attr = curses.color_pair(1) if write_scope == "any" else curses.A_NORMAL
                    self._popup_add_cells(win, row + 1, 2, prefix, box_w - 4)
                    self._popup_add_cells(
                        win,
                        row + 1,
                        2 + len(prefix),
                        write_scope,
                        box_w - 4 - len(prefix),
                        attr,
                    )
                elif line.startswith("[g] group:"):
                    prefix = "[g] group:  "
                    if self.permission_group:
                        attr = self._permission_group_display_attr() if use_selected_group else curses.color_pair(3)
                    else:
                        attr = disabled_attr
                    self._popup_add_cells(win, row + 1, 2, prefix, box_w - 4)
                    self._popup_add_cells(
                        win,
                        row + 1,
                        2 + len(prefix),
                        group_value,
                        box_w - 4 - len(prefix),
                        attr,
                    )
                else:
                    self._popup_add_cells(win, row + 1, 2, line, box_w - 4)
            win.refresh()
            key = self.stdscr.getch()
            if key in (ord("r"), ord("R")):
                read_index = (read_index + 1) % len(PERMISSION_READ_ORDER)
                next_read_scope = PERMISSION_READ_ORDER[read_index]
                if PERMISSION_READ_ORDER.index(write_scope) > read_index:
                    write_scope = next_read_scope
                continue
            if key == ord("w"):
                if write_scope == "pvt":
                    write_scope = "grp"
                    if read_scope == "pvt":
                        read_index = PERMISSION_READ_ORDER.index("grp")
                else:
                    write_scope = "pvt"
                continue
            if key == ord("W"):
                if read_scope == "any":
                    write_scope = "any" if write_scope != "any" else "grp"
                continue
            if key in (ord("g"), ord("G")):
                if self.permission_group:
                    use_selected_group = not use_selected_group
                continue
            if key == ord("y"):
                return mode, effective_group
            if key == 27:
                return None

    def _show_help_popup(self) -> None:
        lines = [
            "Up / Down          Move cursor",
            "Left               Collapse directory / go to parent",
            "Right / Enter      Expand directory / enter first child",
            "                   Or expand pagination on '... more'",
            "Space              Toggle selection (file or whole subtree)",
            "Mouse wheel        Move cursor up/down",
            "Mouse click        Move cursor to row",
            "Checkbox click     Toggle row selection",
            "Double click       Expand/collapse directory",
            "d                  Download selected  (remote → local)",
            "u                  Upload selected    (local → remote)",
            "f                  Preview diff in built-in popup (red entries only)",
            "F                  Preview diff with external viewer (vim -d by default)",
            "o                  Open local file with configured editor",
            "O                  Open remote temp copy; changed copy can upload",
            "p                  Configure remote permissions for selected entries",
            "P                  Cycle PERM column: badge / owner / group / mode",
            "c                  Configure and check selected entries",
            "x                  Clear all selections (with confirmation)",
            "r                  Refresh manifests",
            "?                  Show this help",
            "q                  Quit",
            "",
            "Colors",
            "  white            Both sides exist, not fully explored",
            "  yellow           Local only",
            "  blue             Remote only",
            "  green            Confirmed identical (size + mtime match)",
            "  red              Different (size or mtime differ)",
            "",
            "Pagination",
            f"  Shows up to {self.pagination_size} items per directory",
            "  '... N more' can be expanded with Right/Enter or click",
            "",
            "PERM column (middle column)",
            "  [pvt:-]          Owner only",
            "  [grp:r]          Owner + group read",
            "  [grp:w]          Owner + group write",
            "  [any:r]          Owner + group + other read",
            "  [any:g]          Owner + group write, other read",
            "  [any:w]          Owner + group + other write",
            "  [ 755 ]          Non-standard numeric mode",
            "",
            "Diff preview",
            "  f uses built-in popup with Left/Right horizontal pan",
            "  F uses vim -d by default, or configured diff viewer",
            "",
            "File open",
            "  file_editor supports {file}, e.g. vim {file}",
            "  image_opener supports {file}, defaults to foreground timg",
            "  timg stays open until Ctrl+C returns to the TUI",
            "  If timg is unavailable, image files fall back to file_editor",
            "  Default GUI opener is view-only for remote temp copies",
            "  Changed remote temp copies ask y/n before single-file upload",
            "",
            "Mouse wheel",
            "  mouse_wheel.step controls rows per event",
            "  mouse_wheel.coalesce_ms filters repeated reports",
            "  Default coalesce_ms=0 keeps continuous scrolling smooth",
            "",
            "Remote permissions",
            "  p opens a two-dimensional permission editor",
            "  read: pvt / grp / any",
            "  write: pvt / grp",
            "  group: selected group / not change group (grp only)",
            "",
            "Check",
            "  c opens a confirmation line with m/depth/y/n/? controls",
            "  ignore metadata is on by default",
            "  stop depth is relative to each selected root",
        ]
        self._show_popup("Help", lines)

    def _try_preview_diff(self, *, external: bool = False) -> None:
        """Gate-check then launch diff preview for the node under the cursor."""
        node = self.current_node()
        if node is None:
            return
        if node_is_directory(node):
            self.message = "Diff preview is only available for files, not directories."
            return
        if not node_exists_on_left(node) or not node_exists_on_right(node):
            self.message = "Diff preview requires the file to exist on both sides."
            return
        if not node_has_self_difference(node):
            self.message = "File appears identical on both sides (same size and mtime)."
            return
        self._preview_diff(node, external=external)

    def _available_diff_viewer(self) -> str | None:
        for command in self.diff_viewers:
            try:
                argv = shlex.split(command)
            except ValueError:
                continue
            if (
                argv
                and is_supported_external_diff_viewer(command)
                and shutil.which(argv[0]) is not None
            ):
                return command
        return None

    def _run_external_diff_viewer(
        self,
        viewer_command: str,
        local_path: Path,
        remote_copy_path: Path,
        diff_text: str,
    ) -> bool:
        try:
            argv = shlex.split(viewer_command)
        except ValueError as exc:
            self.message = f"Invalid diff viewer command: {exc}"
            return False
        if not argv:
            return False
        if not is_supported_external_diff_viewer(viewer_command):
            self.message = "Unsupported diff viewer. Use vim -d, vimdiff, nvim -d, or delta."
            return False

        uses_local = any("{local}" in part for part in argv)
        uses_remote = any("{remote}" in part for part in argv)
        uses_diff = any("{diff}" in part for part in argv)
        diff_file_path: Path | None = None
        try:
            if uses_diff:
                with tempfile.NamedTemporaryFile(
                    "w", delete=False, suffix=".diff", encoding="utf-8"
                ) as diff_file:
                    diff_file.write(diff_text)
                    diff_file_path = Path(diff_file.name)
            format_values = {
                "local": str(local_path),
                "remote": str(remote_copy_path),
                "diff": str(diff_file_path) if diff_file_path is not None else "",
            }
            try:
                command = [part.format(**format_values) for part in argv]
            except (KeyError, ValueError) as exc:
                self.message = f"Invalid diff viewer placeholder: {exc}"
                return False
            stdin_text = None if uses_local or uses_remote or uses_diff else diff_text

            self.suspend_tui()
            try:
                subprocess.run(command, input=stdin_text, text=stdin_text is not None)
            finally:
                self.resume_tui()
            return True
        finally:
            if diff_file_path is not None:
                diff_file_path.unlink(missing_ok=True)

    def _show_external_diff(self, local_path: Path, remote_copy_path: Path, diff_text: str) -> bool:
        viewer_command = self._available_diff_viewer()
        if viewer_command is None:
            self.message = "No supported external diff viewer found; use f for built-in popup."
            return False
        return self._run_external_diff_viewer(
            viewer_command,
            local_path,
            remote_copy_path,
            diff_text,
        )

    def _preview_diff(self, node: TreeNode, *, external: bool = False) -> None:
        """Fetch the remote copy to a temp file and show unified diff in a popup."""
        local_path = self.local_root / node.rel_path

        self.message = f"Fetching remote {node.rel_path} for diff..."
        self.render()

        with tempfile.NamedTemporaryFile(
            delete=False, suffix=Path(node.name).suffix or ".tmp"
        ) as tmp:
            tmp_path = Path(tmp.name)

        try:
            tmp_path.write_bytes(self._fetch_remote_file_bytes(node.rel_path))

            diff_result = subprocess.run(
                [
                    "diff", "-u",
                    "--label", f"local/{node.rel_path}",
                    "--label", f"remote/{node.rel_path}",
                    str(local_path),
                    str(tmp_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            lines = diff_result.stdout.splitlines()
            if not lines:
                # diff exit 0 → identical content (mtime differs but bytes same)
                node.content_verified_same = True
                clear_ancestor_caches(node)
                lines = ["(files are byte-identical; only metadata differs)"]
                self._show_popup(f"diff  {node.rel_path}", lines)
            elif external:
                self._show_external_diff(local_path, tmp_path, diff_result.stdout)
            else:
                self._show_popup(f"diff  {node.rel_path}", lines)
            self.message = f"Diff preview closed for {node.rel_path}."
        except (OSError, subprocess.CalledProcessError) as exc:
            err = (
                exc.stderr.decode(errors="replace").strip()
                if isinstance(exc, subprocess.CalledProcessError) and exc.stderr
                else str(exc)
            )
            self._show_popup(
                "Diff Error", ["Failed to fetch remote file:", err or "(no output)"]
            )
            self.message = f"Diff failed for {node.rel_path}."
        finally:
            tmp_path.unlink(missing_ok=True)

    # ------------------------------- key events ----------------------------- #

    def _handle_pending_check_key(self, key: int) -> None:
        if key == ord("y"):
            self.execute_pending_action()
            return
        if key == ord("n"):
            self.pending_action = None
            self.message = "Cancelled pending check."
            return
        if key == ord("m"):
            self.pending_check_ignore_metadata = not getattr(
                self, "pending_check_ignore_metadata", True
            )
            return
        if ord("0") <= key <= ord("9"):
            self.pending_check_stop_depth_text = (
                getattr(self, "pending_check_stop_depth_text", "") + chr(key)
            )
            return
        backspace_keys = {8, 127}
        curses_backspace = getattr(curses, "KEY_BACKSPACE", -1)
        if curses_backspace != -1:
            backspace_keys.add(curses_backspace)
        if key in backspace_keys:
            self.pending_check_stop_depth_text = getattr(
                self, "pending_check_stop_depth_text", ""
            )[:-1]
            return
        if key == ord("?"):
            self._show_check_help_popup()
            return

    def _show_check_help_popup(self) -> None:
        self._show_popup(
            "check help",
            [
                "Check options:",
                "  m      toggle ignore metadata",
                "  0-9    set stop depth",
                "  Backspace deletes the last depth digit",
                "  y      run check",
                "  n      cancel check",
                "",
                "Depth is relative to each selected root.",
                "",
                "Example:",
                "  dataset/              depth 0",
                "    scene_a/            depth 1",
                "      camera/           depth 2",
                "        0001.png        depth 3",
                "        0002.png        depth 3",
                "      labels/           depth 2",
                "    scene_b/            depth 1",
                "",
                "With stop depth 1, the first remote-only, type conflict,",
                "or content difference under scene_a marks the discovered",
                "path and ancestors, skips unchecked siblings under scene_a,",
                "then continues with scene_b. Local-only does not short-circuit.",
            ],
        )

    def handle_key(self, key: int) -> None:
        if self.pending_action is not None:
            if self.pending_action == "check":
                self._handle_pending_check_key(key)
                return
            if key == ord("y"):
                if (
                    self.pending_action == "permission"
                    and self.pending_permission is not None
                    and normalize_permission_mode(self.pending_permission.mode) == "any:any"
                    and not getattr(self, "pending_permission_any_write_confirmed", False)
                ):
                    self.pending_permission_any_write_confirmed = True
                    self.message = (
                        "Other writable is dangerous. Press y again to execute, n to cancel."
                    )
                    return
                self.execute_pending_action()
            elif key == ord("n"):
                cancelled_action = self.pending_action
                self.pending_action = None
                self.pending_permission = None
                self.pending_permission_any_write_confirmed = False
                pending_remote_edit_upload = getattr(
                    self,
                    "pending_remote_edit_upload",
                    None,
                )
                if pending_remote_edit_upload is not None:
                    shutil.rmtree(
                        pending_remote_edit_upload.temp_root,
                        ignore_errors=True,
                    )
                    self.pending_remote_edit_upload = None
                if cancelled_action == "permission":
                    self.message = "Cancelled pending permission action."
                elif cancelled_action == "check":
                    self.message = "Cancelled pending check."
                elif cancelled_action == "remote_edit_upload":
                    self.message = "Cancelled remote edit upload."
                else:
                    self.message = "Cancelled pending sync action."
            return  # block all other keys while confirmation is pending

        visible = self._visible_nodes()
        if key == curses.KEY_MOUSE:
            self.handle_mouse_event()
            return
        if key == curses.KEY_UP:
            self.cursor_index = max(self.cursor_index - 1, 0)
            self.ensure_cursor_visible()
            return
        if key == curses.KEY_DOWN:
            self.cursor_index = min(self.cursor_index + 1, max(len(visible) - 1, 0))
            self.ensure_cursor_visible()
            return
        if key == curses.KEY_LEFT:
            self.collapse_or_move_to_parent()
            return
        if key in (curses.KEY_RIGHT, ord("\n")):
            self.expand_or_move_to_child()
            return
        if key == ord(" "):
            self.toggle_current_node()
            return
        if key == ord("d"):
            self.start_action("download")
            return
        if key == ord("u"):
            self.start_action("upload")
            return
        if key == ord("c"):
            self.start_action("check")
            return
        if key == ord("r"):
            self.message = "Refreshing manifests..."
            self.refresh_manifests(initial_load=False)
            return
        if key == ord("f"):
            self._try_preview_diff()
            return
        if key == ord("F"):
            self._try_preview_diff(external=True)
            return
        if key == ord("o"):
            self._try_open_local_file()
            return
        if key == ord("O"):
            self._try_open_remote_file()
            return
        if key == ord("p"):
            self.start_action("permission")
            return
        if key == ord("P"):
            current = getattr(self, "permission_view", "badge")
            try:
                current_index = PERMISSION_VIEWS.index(current)
            except ValueError:
                current_index = 0
            self.permission_view = PERMISSION_VIEWS[(current_index + 1) % len(PERMISSION_VIEWS)]
            self.message = f"PERM column: {self.permission_view}"
            return
        if key == ord("x"):
            self.start_action("clear")
            return
        if key == ord("?"):
            self._show_help_popup()
            return


# ------------------------------------------------------------------------ #
#                                   entry                                   #
# ------------------------------------------------------------------------ #


def main() -> None:
    args = parse_args()

    if args.update:
        perform_self_update()
        return

    config = resolve_app_config(args)
    maybe_prompt_for_cached_auto_update(config.config_path, config.config_data)
    start_background_auto_update_check(config.config_path, config.config_data)
    if not config.local_root.exists():
        raise FileNotFoundError(f"Local root does not exist: {config.local_root}")
    if config.remote_is_local and not Path(config.remote_spec).exists():
        raise FileNotFoundError(f"Local remote path does not exist: {config.remote_spec}")
    preflight(config.local_root, require_ssh=not config.remote_is_local)

    os.environ.setdefault("TERM", "xterm-256color")
    app = SyncApp(config)
    if app.initial_connection_ok:
        record_successful_connection(
            config.config_path,
            config.config_data,
            config.local_root,
            config.remote_spec,
            config.permission_group,
        )
    app.run()


if __name__ == "__main__":
    main()
