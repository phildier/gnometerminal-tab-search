"""Fuzzy tab switcher for GNOME Terminal."""

import subprocess
import sys

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi


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
    """Return list of (display_name, tab_index, dbus_window_path) tuples."""
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
                tabs.append((display, tab_idx, dbus_window))

    return tabs


def switch_tab(dbus_window, tab_index):
    subprocess.run([
        'gdbus', 'call', '--session',
        '--dest', 'org.gnome.Terminal',
        '--object-path', dbus_window,
        '--method', 'org.gtk.Actions.SetState',
        'active-tab', f'<int32 {tab_index}>', '{}',
    ], capture_output=True)

    subprocess.run(
        ['xdotool', 'search', '--class', 'gnome-terminal-server',
         'windowactivate', '--sync'],
        capture_output=True,
    )


def main():
    tabs = get_tabs()
    if not tabs:
        sys.exit('No GNOME Terminal tabs found.')

    result = subprocess.run(
        ['rofi', '-dmenu', '-p', 'tab:', '-i', '-format', 'i',
         '-no-custom', '-matching', 'fuzzy'],
        input='\n'.join(t[0] for t in tabs),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0 or not result.stdout.strip():
        sys.exit(0)

    display, tab_index, dbus_window = tabs[int(result.stdout.strip())]
    switch_tab(dbus_window, tab_index)


if __name__ == '__main__':
    main()
