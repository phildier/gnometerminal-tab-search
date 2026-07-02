"""Fuzzy tab switcher + directory launcher for GNOME Terminal and Ghostty."""

import html
import subprocess
import sys
from pathlib import Path

from tab_search_core import (
    ConfigError,
    build_picker_entries,
    discover_first_level_directories,
    load_launcher_config,
)
from terminal_backends import GnomeTerminalBackend


def create_backend(launcher_config):
    return GnomeTerminalBackend()


def rofi_row_text(entry):
    text = html.escape(entry.display_name)
    if entry.kind == 'tab':
        return f"<span weight='bold'>{text}</span>"
    return text


def main():
    config_path = Path.home() / '.config' / 'gnometerminal-tab-search' / 'config.toml'
    try:
        launcher_config = load_launcher_config(config_path)
    except ConfigError as exc:
        sys.exit(f"Invalid config at '{config_path}': {exc}")

    backend = create_backend(launcher_config)

    try:
        tabs = backend.get_tabs()
    except Exception:
        tabs = []

    directories = []
    if launcher_config is not None:
        directories = discover_first_level_directories(launcher_config.roots)

    entries = build_picker_entries(tabs, directories)
    if not entries:
        if launcher_config is None:
            sys.exit('No terminal tabs found.')
        sys.exit('No terminal tabs or launchable directories found.')

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
        backend.switch_tab(entry.tab)
        return

    if entry.kind == 'directory-to-open':
        post_cd_command = launcher_config.post_cd_command if launcher_config is not None else None
        backend.open_directory(entry.directory.path, post_cd_command)
        return

    sys.exit(f'Unsupported picker entry type: {entry.kind}')


if __name__ == '__main__':
    main()
