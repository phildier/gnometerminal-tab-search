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

### Task 1: Spike — verify Ghostty tab switching via AT-SPI grab_focus() [GATE]

Throwaway script in `/tmp/opencode` (never committed). Find a non-selected Ghostty `page tab` node, call `grab_focus()`, observe with the user watching whether the tab switches. Also note whether `xdotool windowactivate` is needed to raise the window.

- Pass → proceed with full plan.
- Fail → try `grab_focus()` on the tab's inner label, then on the target tab's terminal panel. If all fail: Ghostty is launcher-only, Task 5 returns `[]`, Task 6 is dropped; check in with the user before continuing.

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
- `pick_window_id_by_name(candidates: list[tuple[str, str]], target_name: str) -> str | None`: match window title against target frame name; fallback first candidate; empty → None.

### Task 4: Refactor — extract `GnomeTerminalBackend`

**Files:** Create `terminal_backends.py`; modify `tab-search.py`, `tests/test_tab_search_runtime.py`.

- Move `get_tabs`, `switch_tab`, `focus_terminal_window`, `get_live_dbus_window_numbers`, env harvesting, `open_directory_in_terminal` into `GnomeTerminalBackend` with interface `get_tabs()/switch_tab(tab)/open_directory(directory, post_cd_command)`.
- Pure refactor: all existing tests green before and after; runtime tests re-target the backend.

### Task 5: `GhosttyBackend.get_tabs()`

**Files:** Modify `terminal_backends.py`; create `tests/test_ghostty_backend.py`.

- AT-SPI walk: app named `ghostty`; per frame collect `page tab` nodes from `page tab list`s that contain `page tab` children (filters the tab-overview widget); frames without a tab list yield one entry named by the frame (hidden tab bar).
- `GhosttyTabEntry` dataclass (backend-local): display_name, raw_name, tab node (or None), frame name.
- Multi-window `[window-name]` prefix mirrors GNOME behavior.
- Tests use stub node objects (get_role_name/get_name/get_child_count/get_child_at_index).

### Task 6: `GhosttyBackend.switch_tab()` + window focus

**Files:** Modify `terminal_backends.py`, `tests/test_ghostty_backend.py`.

- `grab_focus()` on stored node (mechanism per Task 1 outcome); then `xdotool search --class ghostty`, `xprop _NET_WM_NAME` per window, `pick_window_id_by_name`, `xdotool windowactivate --sync`.
- Hidden-tab-bar entries: window activation only.

### Task 7: `GhosttyBackend.open_directory()`

**Files:** Modify `terminal_backends.py`, `tests/test_ghostty_backend.py`.

- Run `build_ghostty_launch_command(...)`; non-zero exit → `sys.exit` with stderr; success → focus window. No fallback chain.

### Task 8: Wire backend selection into `main()`

**Files:** Modify `terminal_backends.py`, `tab-search.py`, `tests/test_tab_search_runtime.py`.

- `create_backend(config)` → `GnomeTerminalBackend` when config is None or `terminal == "gnome-terminal"`, else `GhosttyBackend`.
- `main()` uses `backend.get_tabs()`, `backend.switch_tab(entry.tab)`, `backend.open_directory(...)`.
- Tests: selection logic + mocked end-to-end flow per backend.

### Task 9: Docs

**Files:** Modify `README.md`.

- Document `terminal` key, optional `roots` (home default), Ghostty support and mechanisms; fix WM_CLASS docs drift (`Gnome-terminal` not `gnome-terminal-server`); note Ghostty install is user-managed.
