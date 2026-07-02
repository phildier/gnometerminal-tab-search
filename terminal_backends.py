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

from tab_search_core import (
    TabEntry,
    assign_dbus_window_paths,
    build_gnome_terminal_commands,
    build_terminal_launch_env,
    command_result_is_success,
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
    root_pids = get_pids_matching(root_pattern)
    if not root_pids:
        return []

    process_table = get_process_table()
    descendant_pids = sorted(get_descendant_pids(root_pids, process_table))

    environments = []
    for pid in descendant_pids:
        environment = read_process_environment(pid)
        if environment:
            environments.append(environment)
    return environments


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
