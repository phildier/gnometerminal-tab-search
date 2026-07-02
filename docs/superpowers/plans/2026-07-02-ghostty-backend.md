# Ghostty Backend Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Selectable terminal backend (`gnome-terminal` default, `ghostty`) via config, with full parity: tab listing, tab switching, directory launching.

**Architecture:** Backend classes in new `terminal_backends.py` behind a duck-typed interface; pure helpers stay in `tab_search_core.py`; `main()` selects a backend from config.

**Tech Stack:** Python 3.11+ stdlib, system PyGObject (AT-SPI), rofi, gdbus, xdotool, ghostty CLI.

## Global Constraints

- Python 3.11+; no new dependencies.
- Configs without `terminal` must behave exactly as today.
- Runtime tests fake `gi` in `sys.modules`; CI must not need system packages.
- Spec: `docs/superpowers/specs/2026-07-02-ghostty-backend-design.md`.
- TDD per task; commit per task.

---

### Task 0: Build Ghostty from HEAD

Build upstream Ghostty HEAD (clone already at `/tmp/opencode/ghostty`; requires Zig >= minimum_zig_version from `build.zig.zon`, currently 0.15.2) and install to `~/.local` (or user preference). User switches their running Ghostty to the new build before Task 1. Not part of the repo; no commit.

> Note (2026-07-02): AT-SPI `grab_focus()` was spiked first and failed with `atspi_error (1)` on every node variant. The mechanism below (`GHOSTTY_SURFACE_ID` + `present-surface`) replaces it; it requires Ghostty HEAD.

### Task 1: Spike — verify surface-ID harvesting + present-surface switching [GATE]

Throwaway script in `/tmp/opencode` (never committed), run against the HEAD build with the user watching:

1. Harvest `GHOSTTY_SURFACE_ID` + `PWD` from `/proc/<pid>/environ` of Ghostty child shells (pgrep/ps descendant walk, as the tool already does for GNOME Terminal).
2. Pick a surface belonging to a non-active tab; call `gdbus call --session --dest com.mitchellh.ghostty --object-path /com/mitchellh/ghostty --method org.gtk.Actions.Activate present-surface '[<uint64 ID>]' '{}'`.
3. Confirm the tab switches and the window raises. Also validate the tab-to-surface matching strategy (PWD vs AT-SPI title).

- Pass → proceed with full plan.
- Fail → check in with the user before continuing (fallback: launcher-only Ghostty).

### Task 2: Config — `terminal` key + optional `roots` defaulting to `[~]`

**Files:** Modify `tab_search_core.py`, `tests/test_tab_search_core.py`.

- `LauncherConfig` gains `terminal: str = "gnome-terminal"`.
- Validation: `terminal` must be in `{"gnome-terminal", "ghostty"}`, else `ConfigError` listing valid values.
- `roots` absent → `[Path.home()]`. Present → existing validation (non-empty list of existing directory strings).
- Tests: default when absent, both accepted values, unknown rejected, terminal-only config valid with home root, roots-only config back-compat.

### Task 3: Core — Ghostty pure helpers

**Files:** Modify `tab_search_core.py`, `tests/test_tab_search_core.py`.

- Extract shared `build_cd_script(directory, post_cd_command)` used by both backends' bash launch paths.
- `build_ghostty_launch_command(directory, post_cd_command=None) -> list[str]`:
  - without post command: `["ghostty", "+new-window", f"--working-directory={directory}"]`
  - with: `["ghostty", "+new-window", "-e", "bash", "-ic", script]`
- `collect_ghostty_surfaces(environments: list[dict[str, str]]) -> list[GhosttySurface]`: extract `(surface_id: int, pwd: str)` pairs from environments containing `GHOSTTY_SURFACE_ID` (hex `0x...` format, parse to int). Skip malformed values.
- `match_tab_to_surface(tab_name: str, surfaces: list[GhosttySurface]) -> int | None`: match an AT-SPI tab title to a surface ID (exact strategy per Task 1 spike findings — expected: tab title equals `PWD` with `~` abbreviation; compare expanded paths).

### Task 4: Refactor — extract `GnomeTerminalBackend`

**Files:** Create `terminal_backends.py`; modify `tab-search.py`, `tests/test_tab_search_runtime.py`.

- Move `get_tabs`, `switch_tab`, `focus_terminal_window`, `get_live_dbus_window_numbers`, env harvesting, `open_directory_in_terminal` into `GnomeTerminalBackend` with interface `get_tabs()/switch_tab(tab)/open_directory(directory, post_cd_command)`.
- Pure refactor: all existing tests green before and after; runtime tests re-target the backend.

### Task 5: `GhosttyBackend.get_tabs()`

**Files:** Modify `terminal_backends.py`; create `tests/test_ghostty_backend.py`.

- AT-SPI walk: app named `ghostty`; per frame collect `page tab` nodes from `page tab list`s that contain `page tab` children (filters the tab-overview widget); frames without a tab list yield one entry named by the frame (hidden tab bar).
- Harvest surfaces once via `collect_ghostty_surfaces(get_terminal_child_environments(...))` (process-root: pgrep for the ghostty binary); resolve each tab's surface ID with `match_tab_to_surface`.
- `GhosttyTabEntry` dataclass: display_name, raw_name, surface_id (int | None).
- If no environment contains `GHOSTTY_SURFACE_ID` (pre-HEAD Ghostty), return `[]` (launcher-only degradation per spec). Tabs whose surface can't be matched are omitted.
- Multi-window `[window-name]` prefix mirrors GNOME behavior.
- Tests use stub node objects (get_role_name/get_name/get_child_count/get_child_at_index) and fake environments.

### Task 6: `GhosttyBackend.switch_tab()`

**Files:** Modify `terminal_backends.py`, `tests/test_ghostty_backend.py`.

- `gdbus call --session --dest com.mitchellh.ghostty --object-path /com/mitchellh/ghostty --method org.gtk.Actions.Activate present-surface '[<uint64 N>]' '{}'` with the entry's surface ID. present-surface raises the window itself; add xdotool activation only if the Task 1 spike shows it is needed.

### Task 7: `GhosttyBackend.open_directory()`

**Files:** Modify `terminal_backends.py`, `tests/test_ghostty_backend.py`.

- Run `build_ghostty_launch_command(...)`; non-zero exit → `sys.exit` with stderr; success → focus the Ghostty window via xdotool (`--class ghostty`). No fallback chain.

### Task 8: Wire backend selection into `main()`

**Files:** Modify `terminal_backends.py`, `tab-search.py`, `tests/test_tab_search_runtime.py`.

- `create_backend(config)` → `GnomeTerminalBackend` when config is None or `terminal == "gnome-terminal"`, else `GhosttyBackend`.
- `main()` uses `backend.get_tabs()`, `backend.switch_tab(entry.tab)`, `backend.open_directory(...)`.
- Tests: selection logic + mocked end-to-end flow per backend.

### Task 9: Docs

**Files:** Modify `README.md`.

- Document `terminal` key, optional `roots` (home default), Ghostty support and mechanisms; fix WM_CLASS docs drift (`Gnome-terminal` not `gnome-terminal-server`); note Ghostty install is user-managed.
