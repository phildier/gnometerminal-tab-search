# gnometerminal-tab-search

A keyboard-triggered fuzzy workspace/tab switcher + directory launcher for GNOME Terminal, Ghostty, and Herdr. Press a hotkey from anywhere on the desktop and one rofi fuzzy-search popup lists open terminal tabs or Herdr workspaces plus unopened first-level directories from your configured roots.

## How it works

The terminal backend is selected by the optional `terminal` config key (`gnome-terminal` is the default; `ghostty` and `herdr` are supported).

### GNOME Terminal backend

**Tab enumeration** — GNOME Terminal does not expose tab titles over DBus. The `org.gnome.Terminal.Terminal0` interface has no readable properties for this. The only reliable path is the AT-SPI accessibility tree, read via the Python `gi`/`Atspi` bindings.

**Tab switching** — a `gdbus call` on `org.gtk.Actions.SetState` with the `active-tab` action and an integer index, targeting the live `/org/gnome/Terminal/window/N` paths discovered via D-Bus introspection (window numbers are never reused after a window closes).

**Directory launch** — when a directory is selected, the script harvests `GNOME_TERMINAL_SERVICE` and `GNOME_TERMINAL_SCREEN` from an existing GNOME Terminal child process and uses them to remote `gnome-terminal --tab --working-directory=...` into the running terminal server. If a global `post_cd_command` is configured, the launch path switches to `bash -ic` so bash functions sourced by `~/.bashrc` are available. If no terminal process is available, it falls back to opening a new window.

**Window focus** — `xdotool search --class Gnome-terminal`, then `xprop` disambiguates the visible top-level window from the server window before `xdotool windowactivate --sync`.

### Ghostty backend

**Requires a Ghostty build newer than 1.3.1** (HEAD as of mid-2026): tab switching depends on `GHOSTTY_SURFACE_ID`, which released versions do not yet export. On older builds the picker degrades gracefully to directory launching only.

**Tab enumeration** — AT-SPI, like GNOME Terminal. Windows with a single tab hide the tab bar and are listed by window title instead.

**Tab switching** — Ghostty exposes no tab-switch action over D-Bus, but it has an app-level `present-surface(uint64)` action that raises the window and focuses the surface's tab. Surface IDs are harvested from `GHOSTTY_SURFACE_ID` in `/proc/<pid>/environ` of Ghostty's child shells, and each tab title is matched to a surface by the shell's live working directory (`/proc/<pid>/cwd`).

**Directory launch** — stock Ghostty only exposes `new-window` over IPC; it has no way to remotely open a *tab* with a chosen working directory (the window-level `new-tab` D-Bus action takes no parameters). This repo ships a small Ghostty patch (`docs/ghostty-new-tab-dbus-action.patch`, ~55 lines) adding app-level `new-tab`/`new-tab-command` D-Bus actions that mirror `new-window-command` but open the surface as a tab in the most recently focused window. When the running Ghostty exposes `new-tab-command`, directory launches open as tabs (GNOME Terminal parity); otherwise the tool falls back to `ghostty +new-window`. With a `post_cd_command`, either path launches through `-e bash -ic ...`.

To apply the patch when building Ghostty from source:

```bash
git -C ghostty apply /path/to/gnometerminal-tab-search/docs/ghostty-new-tab-dbus-action.patch
zig build -Doptimize=ReleaseFast -fno-sys=gtk4-layer-shell --prefix ~/.local/ghostty-head
```

**Single-instance caveat** — Ghostty registers `com.mitchellh.ghostty` as a D-Bus activatable service backed by a systemd user unit. If you run a self-built Ghostty while a distro package is also installed, D-Bus activation can start the packaged binary behind your back and claim the bus name; the self-built instance then never owns it and `present-surface` calls go to an invisible instance. Do not mask the activation unit — GNOME Shell launches the app through D-Bus activation, and a masked unit makes launching fail silently. Instead, override the unit to point at your build:

```ini
# ~/.config/systemd/user/app-com.mitchellh.ghostty.service
[Unit]
Description=Ghostty (HEAD build)
After=graphical-session.target
After=dbus.socket
Requires=dbus.socket

[Service]
Type=notify-reload
ReloadSignal=SIGUSR2
BusName=com.mitchellh.ghostty
ExecStart=%h/.local/ghostty-head/bin/ghostty --gtk-single-instance=true

[Install]
WantedBy=graphical-session.target
```

then `systemctl --user daemon-reload`. Pair it with a user-level desktop entry (`~/.local/share/applications/com.mitchellh.ghostty.desktop`, copied from the system one) whose `Exec`/`TryExec` point at the same binary, keeping `DBusActivatable=true`.

### Herdr backend

**Requires Herdr 0.7.3 or newer** and a running default or named session.

**Workspace enumeration** - `herdr api snapshot` supplies workspace labels,
stable IDs, worktree checkout paths, and pane working directories as JSON.

**Workspace switching** - `herdr workspace focus <id>` selects the workspace,
then `xdotool` activates a dedicated top-level window whose exact title is
`herdr`. A Herdr client nested in an arbitrary terminal tab and multiple Herdr
client windows are not currently supported.

**Directory launch** - `herdr workspace create --cwd <directory> --label
<basename> --focus` creates and focuses a workspace. A nonblank
`post_cd_command` is then run in the new root pane through `bash -ic`.
The launcher reports an error when the configured Herdr session is not running;
it does not start a headless server.

### All backends

**Directory discovery** — when `~/.config/gnometerminal-tab-search/config.toml` exists, immediate child directories from the configured roots are added to the picker when they are not already represented by an open tab or workspace.

**Multi-window support (GNOME Terminal and Ghostty only)** — when more than one terminal window is open, tab names are prefixed with `[window-title]` to disambiguate.

**Dedupe + precedence** — GNOME Terminal and Ghostty match directory names to tab titles. Herdr uses the worktree checkout basename, then the first pane CWD basename, then the workspace label. When multiple configured roots contain the same first-level basename, the earliest root in the config wins.

## Optional config

If `~/.config/gnometerminal-tab-search/config.toml` is missing, the tool behaves as a GNOME Terminal tab switcher only.

```toml
terminal = "herdr"                                     # gnome-terminal, ghostty, or herdr
ghostty_command = "~/.local/ghostty-head/bin/ghostty"   # optional; default "ghostty"
herdr_session = "work"                                 # optional; omit for Herdr's default session

roots = [
  "~/pmg",
  "~/projects",
]

post_cd_command = "my_shell_function"
```

Rules:

- `terminal` selects the backend: `gnome-terminal` (default), `ghostty`, or `herdr`.
- `ghostty_command` points directory launches at a specific Ghostty binary — useful when a self-built Ghostty is not on the hotkey environment's PATH. `~` is expanded.
- `herdr_session` selects a named running Herdr session. Omit it to use Herdr's default session.
- `roots` is optional; when absent it defaults to your home directory. It is ordered; earlier roots take precedence and later duplicate basenames are dropped.
- `post_cd_command` is optional.
- `post_cd_command` is bash-only and is executed after changing into the launched directory.
- because the command runs through bash, shell functions loaded from `~/.bashrc` are supported.

**Python version detection** — the `tab-search` shell wrapper iterates candidate Python binaries (PATH-based names first, then absolute `/usr/bin/python3.x` paths as a fallback) to find one that can `import gi`. This handles systems where asdf/pyenv shims shadow the system Python that has `python3-gi` installed. If no suitable Python is found, the script prints a fix hint and exits with a non-zero status.

## Requirements

- Ubuntu 24.04 or any GNOME desktop on X11, with an X11 terminal window for the selected backend
- `rofi` (fuzzy picker UI)
- `python3-gi` and `gir1.2-atspi-2.0` (AT-SPI Python bindings)
- `xdotool` (window focus)
- `libglib2.0-bin` (provides `gdbus`)
- Python 3.11 or later with `gi` importable (3.11+ needed for config parsing via `tomllib`)
- For the Ghostty backend with tab switching: a Ghostty build newer than 1.3.1 (self-built from HEAD until released). Ghostty installation is not managed by `install.sh`.
- For the Herdr backend: Herdr 0.7.3 or newer. Herdr installation is not managed by `install.sh`.

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
| `tab-search.py` | Runtime orchestration — config load, backend selection, rofi picker |
| `terminal_backends.py` | Backend implementations — GNOME Terminal, Ghostty, and Herdr (AT-SPI, D-Bus, CLI integration, launching) |
| `tab_search_core.py` | Pure core — data model, config parsing, command builders, matching helpers |
| `install.sh` | Installs apt dependencies and registers the GNOME keyboard shortcut |

## Usage without install.sh

If you prefer to wire up the keybinding manually, run `tab-search` directly or point any launcher at it:

```bash
./tab-search
```

## License

MIT
