"""Core helpers for the GNOME Terminal tab searcher."""

from dataclasses import dataclass
from pathlib import Path


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


def build_gnome_terminal_commands(directory: Path) -> list[list[str]]:
    """Build launch commands in preferred order."""
    working_directory = f"--working-directory={directory}"
    return [
        ["gnome-terminal", "--tab", working_directory],
        ["gnome-terminal", working_directory],
    ]


def command_result_is_success(returncode: int, stderr: str) -> bool:
    """Treat GNOME Terminal's screen lookup error as a launch failure."""
    return returncode == 0 and "Error creating terminal" not in stderr
