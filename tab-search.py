"""Fuzzy tab switcher + directory launcher for GNOME Terminal."""

import html
import os
import subprocess
import sys
from pathlib import Path

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

from tab_search_core import (
    ConfigError,
    LauncherConfig,
    TabEntry,
    build_gnome_terminal_commands,
    build_picker_entries,
    build_terminal_launch_env,
    command_result_is_success,
    discover_first_level_directories,
    load_launcher_config,
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


def get_tabs():
    """Return list of open GNOME Terminal tabs."""
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

    for win_idx, frame in enumerate(frames):
        win_name = frame.get_name()
        tab_list = find_role(frame, 'page tab list')
        dbus_window = f'/org/gnome/Terminal/window/{win_idx + 1}'
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


def switch_tab(dbus_window, tab_index):
    subprocess.run([
        'gdbus', 'call', '--session',
        '--dest', 'org.gnome.Terminal',
        '--object-path', dbus_window,
        '--method', 'org.gtk.Actions.SetState',
        'active-tab', f'<int32 {tab_index}>', '{}',
    ], capture_output=True)

    focus_terminal_window()


def focus_terminal_window():
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


def get_terminal_server_pids():
    result = subprocess.run(
        ['pgrep', '-fa', 'gnome-terminal-server'],
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


def get_terminal_child_environments():
    server_pids = get_terminal_server_pids()
    if not server_pids:
        return []

    process_table = get_process_table()
    descendant_pids = sorted(get_descendant_pids(server_pids, process_table))

    environments = []
    for pid in descendant_pids:
        environment = read_process_environment(pid)
        if environment:
            environments.append(environment)
    return environments


def open_directory_in_terminal(directory, post_cd_command=None):
    base_env = build_terminal_launch_env(os.environ)
    remote_terminal_env = pick_remote_terminal_env(get_terminal_child_environments())
    commands = build_gnome_terminal_commands(directory, post_cd_command)

    attempts = []
    if remote_terminal_env:
        attempts.append((commands[0], build_terminal_launch_env(os.environ, remote_terminal_env)))
    attempts.append((commands[1], base_env))

    errors = []
    for command, environment in attempts:
        result = subprocess.run(command, capture_output=True, text=True, env=environment)
        if command_result_is_success(result.returncode, result.stderr):
            focus_terminal_window()
            return
        errors.append(result.stderr.strip() or f"command failed: {' '.join(command)}")

    sys.exit(f"Could not open directory '{directory}': {'; '.join(errors)}")


def rofi_row_text(entry):
    text = html.escape(entry.display_name)
    if entry.kind == 'tab':
        return f"<span weight='bold'>{text}</span>"
    return text


def main():
    try:
        tabs = get_tabs()
    except Exception:
        tabs = []

    config_path = Path.home() / '.config' / 'gnometerminal-tab-search' / 'config.toml'
    try:
        launcher_config = load_launcher_config(config_path)
    except ConfigError as exc:
        sys.exit(f"Invalid config at '{config_path}': {exc}")

    directories = []
    if launcher_config is not None:
        directories = discover_first_level_directories(launcher_config.roots)

    entries = build_picker_entries(tabs, directories)
    if not entries:
        if launcher_config is None:
            sys.exit('No GNOME Terminal tabs found.')
        sys.exit('No GNOME Terminal tabs or launchable directories found.')

    result = subprocess.run(
        ['rofi', '-dmenu', '-p', 'tab:', '-i', '-format', 'i',
         '-no-custom', '-matching', 'fuzzy', '-markup-rows'],
        input='\n'.join(rofi_row_text(entry) for entry in entries),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0 or not result.stdout.strip():
        sys.exit(0)

    entry = entries[int(result.stdout.strip())]
    if entry.kind == 'tab':
        switch_tab(entry.tab.dbus_window, entry.tab.tab_index)
        return

    if entry.kind == 'directory-to-open':
        post_cd_command = launcher_config.post_cd_command if launcher_config is not None else None
        open_directory_in_terminal(entry.directory.path, post_cd_command)
        return

    sys.exit(f'Unsupported picker entry type: {entry.kind}')


if __name__ == '__main__':
    main()
