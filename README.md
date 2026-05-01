# gnometerminal-tab-search

A keyboard-triggered fuzzy tab switcher for GNOME Terminal. Press a hotkey from anywhere on the desktop and a rofi fuzzy-search popup lists every open GNOME Terminal tab by title. Type to filter, press Enter to jump to the selected tab.

## How it works

**Tab enumeration** — GNOME Terminal does not expose tab titles over DBus. The `org.gnome.Terminal.Terminal0` interface has no readable properties for this. The only reliable path is the AT-SPI accessibility tree, read via the Python `gi`/`Atspi` bindings.

**Tab switching** — a `gdbus call` on `org.gtk.Actions.SetState` with the `active-tab` action and an integer index, targeting `/org/gnome/Terminal/window/1`.

**Window focus** — `xdotool search --class gnome-terminal-server windowactivate --sync`.

**Multi-window support** — when more than one GNOME Terminal window is open, tab names are prefixed with `[window-title]` to disambiguate.

**Python version detection** — the `tab-search` shell wrapper iterates candidate Python binaries (PATH-based names first, then absolute `/usr/bin/python3.x` paths as a fallback) to find one that can `import gi`. This handles systems where asdf/pyenv shims shadow the system Python that has `python3-gi` installed. If no suitable Python is found, the script prints a fix hint and exits with a non-zero status.

## Requirements

- Ubuntu 24.04 or any GNOME desktop with GNOME Terminal
- `rofi` (fuzzy picker UI)
- `python3-gi` and `gir1.2-atspi-2.0` (AT-SPI Python bindings)
- `xdotool` (window focus)
- `libglib2.0-bin` (provides `gdbus`)
- Python 3.9 or later with `gi` importable

## Installation

Clone the repository and run the installer. The installer installs apt dependencies and registers the GNOME keyboard shortcut via `gsettings` (persists across reboots via dconf).

```bash
git clone https://github.com/phildier/gnometerminal-tab-search.git
cd gnometerminal-tab-search
./install.sh              # default keybinding: Super+F8
./install.sh '<Super>F9'  # custom keybinding
```

The installer runs:

```
sudo apt install -y rofi python3.12 python3-gi gir1.2-atspi-2.0 xdotool libglib2.0-bin
```

Then registers a GNOME custom shortcut named "Terminal Tab Search" pointing to the `tab-search` script in the cloned directory.

## Keybinding constraints

Some key combinations are unavailable to custom GNOME shortcuts:

- `Super+<letter>` combos (e.g. `Super+i`) are silently intercepted by GNOME Shell and never reach custom keybindings.
- `Ctrl+Alt+F<N>` combos switch virtual terminals at the kernel level — avoid these entirely.

Safe combinations include `Super+F<N>` and `Ctrl+Shift+<key>`. The default is `Super+F8`.

## Changing the keybinding after install

```bash
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ binding '<Super>F9'
```

## Files

| File | Purpose |
|---|---|
| `tab-search` | Shell wrapper — entry point, finds a Python with `gi` available |
| `tab-search.py` | Python logic — AT-SPI tab enumeration, rofi picker, DBus switch |
| `install.sh` | Installs apt dependencies and registers the GNOME keyboard shortcut |

## Usage without install.sh

If you prefer to wire up the keybinding manually, run `tab-search` directly or point any launcher at it:

```bash
./tab-search
```

## License

MIT
