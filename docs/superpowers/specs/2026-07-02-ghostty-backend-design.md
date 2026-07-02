# Ghostty Backend Support — Design

Date: 2026-07-02
Status: Approved (revised: present-surface mechanism replaces grab_focus)

## Goal

Make the terminal backend selectable via a `terminal` key in
`~/.config/gnometerminal-tab-search/config.toml`, supporting
`gnome-terminal` (default) and `ghostty` with full parity: tab listing,
tab switching, and directory launching.

## Verified facts (tested live, 2026-07-02, Ghostty 1.3.1 on Ubuntu/X11)

- Ghostty runs as a single-instance GTK app on D-Bus at
  `com.mitchellh.ghostty`, exposing `org.gtk.Actions`. `goto_tab` exists
  only as an in-app keybind action, but an app-level
  `present-surface(uint64)` D-Bus action exists: it looks up a surface by
  ID and presents it — "This may involve raising the window and switching
  tabs" (src/Surface.zig `presentSurface`).
- In released 1.3.1 surface IDs are not discoverable externally. On
  upstream HEAD (verified in source, `src/Surface.zig`), every surface
  exports `GHOSTTY_SURFACE_ID` (format `0x%016x`, u64) into its child
  process environment, documented as being for IPC over D-Bus. This repo
  targets a HEAD build of Ghostty.
- AT-SPI `grab_focus()` fails with `atspi_error (1)` on every Ghostty node
  variant (page tab, label, panels, content), even with the window
  activated first. Ghostty/GTK4 does not service remote focus requests.
  The AT-SPI Action interface exposes no tab actions. grab_focus is a dead
  end; `present-surface` is the switching mechanism.
- Ghostty tabs appear in the AT-SPI tree as `page tab` nodes (named with
  tab titles, e.g. `~/projects/foo`) under a `page tab list` inside a
  `scroll pane`. Another `page tab list` without `page tab` children also
  exists (tab overview widget) and must be filtered out.
- A Ghostty window with a single tab hides its tab bar: no `page tab list`
  is present. The frame name equals the tab title.
- `ghostty +new-window --working-directory=<dir>` and
  `ghostty +new-window -e bash -ic "<script>"` open windows in the running
  instance via native IPC. The D-Bus service is activatable, so this works
  even when Ghostty is not running. No environment harvesting needed
  (unlike GNOME Terminal).
- All Ghostty X windows share `WM_CLASS "ghostty", "com.mitchellh.ghostty"`.
  Windows are disambiguated by `_NET_WM_NAME`, which matches the AT-SPI
  frame name.

## Decisions

- **Backend selection:** explicit `terminal` config key only, defaulting to
  `"gnome-terminal"`. No auto-detection.
- **Ghostty tab switching:** harvest `GHOSTTY_SURFACE_ID` from
  `/proc/<pid>/environ` of Ghostty child shells (reusing the existing
  env-harvesting machinery built for GNOME Terminal), match the target tab
  to a surface, then call the `present-surface` D-Bus action with the
  surface ID. This raises the window too, so no xdotool focus dance is
  needed for switching. Requires Ghostty built from HEAD (user runs their
  own build); if no `GHOSTTY_SURFACE_ID` is found in any harvested
  environment (older Ghostty), degrade gracefully to launcher-only with no
  tab rows.
- **Tab-to-surface matching:** match by `PWD` from the same environ read
  where possible, falling back to title matching against AT-SPI tab names.
  Exact strategy validated by the Task 1 spike.
- **`roots` becomes optional:** when a config file exists without `roots`,
  default to `[~]`. When `roots` is present it must still be a non-empty
  list of existing directories. No config file at all keeps today's
  behavior (GNOME Terminal, tabs only).

## Architecture

Approach A — backend protocol:

- New module `terminal_backends.py` holds side-effectful backend classes
  with a duck-typed interface (no ABC):

  ```python
  class SomeBackend:
      def get_tabs(self) -> list[TabEntry]: ...
      def switch_tab(self, tab) -> None: ...
      def open_directory(self, directory: Path, post_cd_command: str | None) -> None: ...
  ```

- `GnomeTerminalBackend` wraps the existing verified logic (AT-SPI listing,
  gdbus `active-tab` SetState, env-harvested `gnome-terminal --tab` launch).
- `GhosttyBackend` uses AT-SPI for tab listing, harvested
  `GHOSTTY_SURFACE_ID` + `present-surface` D-Bus for switching, and
  `ghostty +new-window` IPC for launching. Its tab entries carry a surface
  ID (u64) — plain data, so they can live in the core if convenient.
- `tab_search_core.py` stays pure and gains `build_ghostty_launch_command`
  and `pick_window_id_by_name`; the bash launch script builder is shared
  between backends.
- `main()` in `tab-search.py` becomes backend-agnostic via
  `create_backend(config)`.

Rejected alternatives: branching in place (erodes the core/shell split);
separate script per terminal (duplicates rofi/main plumbing).

## Error handling

- Unknown `terminal` value: `ConfigError` listing valid values.
- Ghostty launch failure: exit with stderr message; no fallback chain
  (single-instance IPC has no tab-vs-window env failure mode).
- Broken AT-SPI: existing behavior — empty tab list.
- Ghostty without `GHOSTTY_SURFACE_ID` support (pre-HEAD build):
  launcher-only, no tab rows.

## Testing

- TDD throughout. Runtime tests keep faking `gi` in `sys.modules` so CI
  needs no system packages. Ghostty AT-SPI walking is tested with stub
  node objects. CI matrix unchanged (Python 3.11–3.13).

## Constraints

- Python 3.11+, stdlib + system PyGObject only.
- Backward compatible: configs without `terminal` behave as today.
- X11 only (existing limitation).
