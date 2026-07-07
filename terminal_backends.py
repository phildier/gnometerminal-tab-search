"""Terminal backend implementations for the tab searcher.

Backends share a duck-typed interface:

    get_tabs() -> list of tab entries
    switch_tab(tab) -> None
    open_directory(directory, post_cd_command) -> None
"""

import os
import subprocess
import sys
from pathlib import Path

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

from dataclasses import dataclass

from tab_search_core import (
    TabEntry,
    assign_dbus_window_paths,
    build_ghostty_launch_command,
    build_ghostty_new_tab_arguments,
    build_gnome_terminal_commands,
    format_gvariant_string_array_parameter,
    build_terminal_launch_env,
    collect_ghostty_surfaces,
    command_result_is_success,
    pair_tabs_with_surfaces,
    parse_dbus_window_numbers,
    pick_focus_window_id,
    pick_remote_terminal_env,
)


def find_role(node, role, depth=10):
    if depth == 0:
        return None
    try:
        if node.get_role_name() == role:
            return node
        for i in range(node.get_child_count()):
            child = node.get_child_at_index(i)
            if child:
                result = find_role(child, role, depth - 1)
                if result:
                    return result
    except Exception:
        pass
    return None


def get_process_table():
    result = subprocess.run(
        ['ps', '-eo', 'pid=,ppid='],
        capture_output=True,
        text=True,
    )
    table = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            table[int(parts[0])] = int(parts[1])
    return table


def get_descendant_pids(root_pids, process_table):
    children_by_parent = {}
    for pid, parent_pid in process_table.items():
        children_by_parent.setdefault(parent_pid, []).append(pid)

    descendants = []
    stack = list(root_pids)
    seen = set()
    while stack:
        pid = stack.pop()
        for child_pid in children_by_parent.get(pid, []):
            if child_pid in seen:
                continue
            seen.add(child_pid)
            descendants.append(child_pid)
            stack.append(child_pid)

    return descendants


def read_process_environment(pid):
    try:
        raw = Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
    except OSError:
        return None

    environment = {}
    for item in raw:
        if b'=' not in item:
            continue
        key, value = item.split(b'=', 1)
        environment[key.decode(errors='ignore')] = value.decode(errors='ignore')
    return environment


def get_pids_matching(pattern):
    result = subprocess.run(
        ['pgrep', '-fa', pattern],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []

    pids = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 1)
        if parts:
            pids.append(int(parts[0]))
    return pids


def get_child_environments(root_pattern):
    """Collect environments of all descendants of processes matching a pattern."""
    return [environment for environment, _ in get_child_processes(root_pattern)]


def get_child_processes(root_pattern):
    """Collect (environment, live cwd) of descendants of matching processes."""
    root_pids = get_pids_matching(root_pattern)
    if not root_pids:
        return []

    process_table = get_process_table()
    descendant_pids = sorted(get_descendant_pids(root_pids, process_table))

    processes = []
    for pid in descendant_pids:
        environment = read_process_environment(pid)
        if environment:
            processes.append((environment, read_process_cwd(pid)))
    return processes


def read_process_cwd(pid):
    try:
        return os.readlink(f'/proc/{pid}/cwd')
    except OSError:
        return None


def find_all_roles(node, role, depth=25):
    """Collect all descendants (including node) with the given AT-SPI role."""
    found = []
    if depth == 0 or node is None:
        return found
    try:
        if node.get_role_name() == role:
            found.append(node)
        for i in range(node.get_child_count()):
            child = node.get_child_at_index(i)
            if child:
                found.extend(find_all_roles(child, role, depth - 1))
    except Exception:
        pass
    return found


@dataclass(frozen=True)
class GhosttyTabEntry:
    display_name: str
    raw_name: str
    surface_id: int


class GhosttyBackend:
    """Ghostty: AT-SPI tab listing, present-surface D-Bus switching, +new-window launch.

    Tab switching requires a Ghostty build that exports GHOSTTY_SURFACE_ID
    into child process environments (HEAD as of 2026-07, newer than 1.3.1).
    Without it, get_tabs() returns [] and the picker is launcher-only.
    """

    def __init__(self, ghostty_command='ghostty'):
        self.ghostty_command = ghostty_command

    def get_tabs(self):
        app = self._find_ghostty_app()
        if app is None:
            return []

        surfaces = collect_ghostty_surfaces(get_child_processes('ghostty'))
        if not surfaces:
            return []

        frames = find_all_roles(app, 'frame')
        multi_window = len(frames) > 1

        # Collect every tab title (with its window) first, then pair titles
        # to surfaces globally so each surface is used at most once.
        collected = []
        for frame in frames:
            frame_name = frame.get_name()
            tab_names = []
            for tab_list in find_all_roles(frame, 'page tab list'):
                page_tabs = find_all_roles(tab_list, 'page tab')
                if page_tabs:
                    tab_names = [tab.get_name() for tab in page_tabs]
                    break
            if not tab_names:
                tab_names = [frame_name]
            for name in tab_names:
                collected.append((frame_name, name))

        surface_ids = pair_tabs_with_surfaces(
            [name for _, name in collected], surfaces
        )

        tabs = []
        for (frame_name, name), surface_id in zip(collected, surface_ids):
            if surface_id is None:
                continue
            display = f'[{frame_name}] {name}' if multi_window else name
            tabs.append(
                GhosttyTabEntry(
                    display_name=display,
                    raw_name=name,
                    surface_id=surface_id,
                )
            )

        return tabs

    def switch_tab(self, tab):
        subprocess.run([
            'gdbus', 'call', '--session',
            '--dest', 'com.mitchellh.ghostty',
            '--object-path', '/com/mitchellh/ghostty',
            '--method', 'org.gtk.Actions.Activate',
            'present-surface',
            f'[<uint64 {tab.surface_id}>]',
            '{}',
        ], capture_output=True)

    def open_directory(self, directory, post_cd_command=None):
        if self._supports_new_tab_action():
            arguments = build_ghostty_new_tab_arguments(directory, post_cd_command)
            result = subprocess.run([
                'gdbus', 'call', '--session',
                '--dest', 'com.mitchellh.ghostty',
                '--object-path', '/com/mitchellh/ghostty',
                '--method', 'org.gtk.Actions.Activate',
                'new-tab-command',
                format_gvariant_string_array_parameter(arguments),
                '{}',
            ], capture_output=True, text=True)
            if result.returncode == 0:
                return
            # Fall through to the new-window launch on failure.

        command = build_ghostty_launch_command(directory, post_cd_command, self.ghostty_command)
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            error = result.stderr.strip() or f"command failed: {' '.join(command)}"
            sys.exit(f"Could not open directory '{directory}': {error}")

    def _supports_new_tab_action(self):
        """True when the running Ghostty exposes the patched new-tab-command action."""
        result = subprocess.run([
            'gdbus', 'call', '--session',
            '--dest', 'com.mitchellh.ghostty',
            '--object-path', '/com/mitchellh/ghostty',
            '--method', 'org.gtk.Actions.List',
        ], capture_output=True, text=True)
        return result.returncode == 0 and "'new-tab-command'" in result.stdout

    def _find_ghostty_app(self):
        Atspi.init()
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app and (app.get_name() or '') == 'ghostty':
                return app
        return None


class GnomeTerminalBackend:
    """GNOME Terminal: AT-SPI tab listing, gdbus tab switching, env-remoted launch."""

    def get_tabs(self):
        Atspi.init()
        desktop = Atspi.get_desktop(0)

        frames = []
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if not app or app.get_name() != 'gnome-terminal-server':
                continue
            for j in range(app.get_child_count()):
                frame = app.get_child_at_index(j)
                if frame and find_role(frame, 'page tab list'):
                    frames.append(frame)

        multi_window = len(frames) > 1
        tabs = []
        dbus_window_paths = assign_dbus_window_paths(
            len(frames), self._get_live_dbus_window_numbers()
        )

        for win_idx, frame in enumerate(frames):
            win_name = frame.get_name()
            tab_list = find_role(frame, 'page tab list')
            dbus_window = dbus_window_paths[win_idx]
            for tab_idx in range(tab_list.get_child_count()):
                tab = tab_list.get_child_at_index(tab_idx)
                if tab:
                    name = tab.get_name()
                    display = f'[{win_name}] {name}' if multi_window else name
                    tabs.append(
                        TabEntry(
                            display_name=display,
                            raw_name=name,
                            tab_index=tab_idx,
                            dbus_window=dbus_window,
                        )
                    )

        return tabs

    def switch_tab(self, tab):
        subprocess.run([
            'gdbus', 'call', '--session',
            '--dest', 'org.gnome.Terminal',
            '--object-path', tab.dbus_window,
            '--method', 'org.gtk.Actions.SetState',
            'active-tab', f'<int32 {tab.tab_index}>', '{}',
        ], capture_output=True)

        self._focus_terminal_window()

    def open_directory(self, directory, post_cd_command=None):
        base_env = build_terminal_launch_env(os.environ)
        remote_terminal_env = pick_remote_terminal_env(
            get_child_environments('gnome-terminal-server')
        )
        commands = build_gnome_terminal_commands(directory, post_cd_command)

        attempts = []
        if remote_terminal_env:
            attempts.append(
                (commands[0], build_terminal_launch_env(os.environ, remote_terminal_env))
            )
        attempts.append((commands[1], base_env))

        errors = []
        for command, environment in attempts:
            result = subprocess.run(command, capture_output=True, text=True, env=environment)
            if command_result_is_success(result.returncode, result.stderr):
                self._focus_terminal_window()
                return
            errors.append(result.stderr.strip() or f"command failed: {' '.join(command)}")

        sys.exit(f"Could not open directory '{directory}': {'; '.join(errors)}")

    def _get_live_dbus_window_numbers(self):
        result = subprocess.run(
            [
                'gdbus', 'introspect', '--session',
                '--dest', 'org.gnome.Terminal',
                '--object-path', '/org/gnome/Terminal/window',
                '--xml',
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []
        return parse_dbus_window_numbers(result.stdout)

    def _focus_terminal_window(self):
        search_result = subprocess.run(
            ['xdotool', 'search', '--class', 'Gnome-terminal'],
            capture_output=True,
            text=True,
        )
        if search_result.returncode != 0:
            return

        candidates = []
        for window_id in search_result.stdout.splitlines():
            if not window_id.strip():
                continue
            class_result = subprocess.run(
                ['xprop', '-id', window_id, 'WM_CLASS'],
                capture_output=True,
                text=True,
            )
            candidates.append((window_id, class_result.stdout.strip()))

        focus_window_id = pick_focus_window_id(candidates)
        if not focus_window_id:
            return

        subprocess.run(
            ['xdotool', 'windowactivate', '--sync', focus_window_id],
            capture_output=True,
        )
