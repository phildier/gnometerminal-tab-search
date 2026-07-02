"""Core helpers for the GNOME Terminal tab searcher."""

from dataclasses import dataclass
from pathlib import Path
import shlex
import xml.etree.ElementTree as ElementTree

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised only on older Python versions
    tomllib = None


@dataclass(frozen=True)
class TabEntry:
    display_name: str
    raw_name: str
    tab_index: int
    dbus_window: str


@dataclass(frozen=True)
class DirectoryEntry:
    name: str
    path: Path


@dataclass(frozen=True)
class PickerEntry:
    kind: str
    display_name: str
    tab: TabEntry | None = None
    directory: DirectoryEntry | None = None


SUPPORTED_TERMINALS = ("gnome-terminal", "ghostty")


@dataclass(frozen=True)
class LauncherConfig:
    roots: list[Path]
    post_cd_command: str | None = None
    terminal: str = "gnome-terminal"


class ConfigError(ValueError):
    """Raised when the launcher config exists but is invalid."""


def discover_first_level_directories(roots: list[Path]) -> list[DirectoryEntry]:
    """Discover first-level directories with root-order precedence."""
    chosen: dict[str, DirectoryEntry] = {}

    for root in roots:
        if not root.is_dir():
            continue

        for child in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
            if not child.is_dir() or child.name in chosen:
                continue
            chosen[child.name] = DirectoryEntry(name=child.name, path=child)

    return list(chosen.values())


def load_launcher_config(config_path: Path) -> LauncherConfig | None:
    """Load launcher config when present, or return None when absent."""
    if not config_path.exists():
        return None

    if tomllib is None:
        raise ConfigError("Config parsing requires Python 3.11+.")

    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid config TOML: {exc}") from exc

    roots_value = data.get("roots")
    if roots_value is None:
        roots = [Path.home()]
    else:
        if not isinstance(roots_value, list) or not roots_value or not all(isinstance(item, str) for item in roots_value):
            raise ConfigError("Config 'roots' must be a non-empty list of directory strings.")

        roots = []
        for root_value in roots_value:
            root_path = Path(root_value).expanduser()
            if not root_path.is_dir():
                raise ConfigError(f"Configured root is not a directory: {root_value}")
            roots.append(root_path)

    post_cd_command = data.get("post_cd_command")
    if post_cd_command is not None and not isinstance(post_cd_command, str):
        raise ConfigError("Config 'post_cd_command' must be a string.")

    terminal = data.get("terminal", "gnome-terminal")
    if terminal not in SUPPORTED_TERMINALS:
        raise ConfigError(
            f"Config 'terminal' must be one of: {', '.join(SUPPORTED_TERMINALS)}."
        )

    return LauncherConfig(roots=roots, post_cd_command=post_cd_command, terminal=terminal)


def build_picker_entries(tabs: list[TabEntry], directories: list[DirectoryEntry]) -> list[PickerEntry]:
    """Merge tabs and unopened directories into one picker result list."""
    entries = [PickerEntry(kind="tab", display_name=tab.display_name, tab=tab) for tab in tabs]

    open_tab_names = {tab.raw_name for tab in tabs}
    for directory in directories:
        if directory.name in open_tab_names:
            continue
        entries.append(
            PickerEntry(kind="directory-to-open", display_name=directory.name, directory=directory)
        )

    return entries


def pick_remote_terminal_env(environments: list[dict[str, str]]) -> dict[str, str] | None:
    """Pick the first environment that can remote into an existing GNOME Terminal."""
    for environment in environments:
        service = environment.get("GNOME_TERMINAL_SERVICE")
        screen = environment.get("GNOME_TERMINAL_SCREEN")
        if service and screen:
            return {
                "GNOME_TERMINAL_SERVICE": service,
                "GNOME_TERMINAL_SCREEN": screen,
            }
    return None


def build_terminal_launch_env(
    environment: dict[str, str],
    remote_terminal_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Strip stale GNOME Terminal targeting vars and optionally overlay a live pair."""
    launch_env = dict(environment)
    launch_env.pop("GNOME_TERMINAL_SERVICE", None)
    launch_env.pop("GNOME_TERMINAL_SCREEN", None)

    if remote_terminal_env:
        launch_env.update(remote_terminal_env)

    return launch_env


def build_gnome_terminal_commands(directory: Path, post_cd_command: str | None = None) -> list[list[str]]:
    """Build launch commands in preferred order."""
    if post_cd_command:
        script = f"cd -- {shlex.quote(str(directory))} || exit 1; {post_cd_command}; exec bash -i"
        return [
            ["gnome-terminal", "--tab", "--", "bash", "-ic", script],
            ["gnome-terminal", "--", "bash", "-ic", script],
        ]

    working_directory = f"--working-directory={directory}"
    return [
        ["gnome-terminal", "--tab", working_directory],
        ["gnome-terminal", working_directory],
    ]


def parse_dbus_window_numbers(introspection_xml: str) -> list[int]:
    """Extract live GNOME Terminal window numbers from D-Bus introspection XML."""
    try:
        root = ElementTree.fromstring(introspection_xml)
    except ElementTree.ParseError:
        return []

    numbers = []
    for child in root.findall("node"):
        name = child.get("name", "")
        if name.isdigit():
            numbers.append(int(name))

    return sorted(numbers)


def assign_dbus_window_paths(frame_count: int, live_window_numbers: list[int]) -> list[str]:
    """Map AT-SPI frame order to live D-Bus window paths.

    GNOME Terminal allocates window numbers monotonically and never reuses
    them, so after closing a window the survivors may be numbered 2, 3, ...
    When the live window count matches the frame count, use the live numbers
    in order; otherwise fall back to the historical sequential assumption.
    """
    if len(live_window_numbers) == frame_count:
        numbers = live_window_numbers
    else:
        numbers = list(range(1, frame_count + 1))

    return [f"/org/gnome/Terminal/window/{number}" for number in numbers]


def pick_focus_window_id(candidates: list[tuple[str, str]]) -> str | None:
    """Pick the visible top-level GNOME Terminal window when possible."""
    for window_id, wm_class in candidates:
        if '"Gnome-terminal"' in wm_class:
            return window_id

    if candidates:
        return candidates[0][0]

    return None


def command_result_is_success(returncode: int, stderr: str) -> bool:
    """Treat GNOME Terminal's screen lookup error as a launch failure."""
    return returncode == 0 and "Error creating terminal" not in stderr
