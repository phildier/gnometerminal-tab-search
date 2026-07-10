# Herdr Workspace Backend Support - Design

Date: 2026-07-10
Status: Approved

## Goal

Add Herdr as a selectable backend so the picker can list and focus Herdr
workspaces and create a workspace for a selected directory. Existing GNOME
Terminal and Ghostty behavior must remain unchanged.

## Scope

- Target Herdr workspaces, not Herdr tabs or panes.
- Support the default Herdr session and one explicitly configured named
  session.
- Focus a dedicated top-level X11 terminal window running the Herdr client.
- Preserve directory discovery, deduplication, and `post_cd_command` behavior.
- Do not start a Herdr server when the configured session is unavailable.

Locating a Herdr client nested in an arbitrary GNOME Terminal or Ghostty tab,
and disambiguating multiple Herdr client windows, are out of scope.

## Configuration

`terminal` accepts a new value, `"herdr"`:

```toml
terminal = "herdr"
herdr_session = "work" # optional; omitted means the default session
```

`herdr_session` is optional and valid only as a non-empty string. The backend
omits the global `--session` argument when this setting is absent. The Herdr
executable remains `herdr`; this change does not add a configurable binary
path.

## Architecture

Add `HerdrBackend` to `terminal_backends.py`. It implements the existing
duck-typed backend interface:

```python
get_tabs() -> list[workspace entries]
switch_tab(workspace) -> None
open_directory(directory, post_cd_command) -> None
```

The method names remain unchanged to avoid widening the runtime orchestration
for one backend. A Herdr workspace entry carries its display label, directory
deduplication name, and stable workspace ID.

`create_backend()` constructs `HerdrBackend` when `terminal = "herdr"` and
passes the optional session name. GNOME Terminal remains the default when no
config file exists or no terminal is selected.

## Data Flow

### List workspaces

Run one CLI command:

```text
herdr [--session NAME] api snapshot
```

Parse the JSON response's workspaces and panes. Each picker row uses the
workspace label for display and the workspace ID for later focus. Determine
the row's directory deduplication name from the basename of its worktree
checkout path when available, otherwise from the `cwd` of the first pane for
that workspace in snapshot order. Fall back to the workspace label when
neither path is available.

This keeps renamed workspace labels visible while preventing the corresponding
configured-root directory from appearing as a second launchable row.

### Focus a workspace

Run:

```text
herdr [--session NAME] workspace focus WORKSPACE_ID
```

After success, use `xdotool` to find a top-level X11 window whose title matches
`^herdr$` and activate it synchronously. The design assumes one dedicated
Herdr window. It does not attempt to identify or switch an outer terminal tab.

### Create a workspace

Run:

```text
herdr [--session NAME] workspace create \
  --cwd DIRECTORY --label BASENAME --focus
```

Parse the returned root pane ID. If `post_cd_command` is non-empty, submit a
properly shell-quoted `bash -ic` command to that pane with `herdr pane run`,
using the existing bash launch-script semantics. If `post_cd_command` is
absent or blank, do not send a follow-up command. Finally, activate the
dedicated `herdr` window.

## Error Handling

- A missing or stopped default/named Herdr session is fatal. Show the Herdr
  CLI error and do not start a headless server.
- A non-zero Herdr CLI result, malformed JSON, or an unexpected response shape
  is fatal and includes operation context in the message.
- Failure to find or activate the exact-title `herdr` window after a successful
  focus or create operation is fatal with a clear focus error.
- Herdr failures must not be swallowed by the runtime's existing tolerant tab
  enumeration path. The backend raises `SystemExit` with its user-facing error,
  which is not caught by the runtime's `except Exception` block.

## Testing

Use TDD and mocked subprocess results; CI does not require a running Herdr
server.

- Config tests cover `terminal = "herdr"`, absent and named `herdr_session`
  values, and invalid session types or empty strings.
- Pure tests cover snapshot parsing, workspace entry creation, and checkout
  path / pane CWD / label deduplication precedence.
- Backend tests cover default and named-session command construction, focus,
  exact-title X11 activation, workspace creation, optional post-command
  execution, malformed responses, and command failures.
- Runtime tests verify that `create_backend()` selects `HerdrBackend` and
  passes the configured session.
- Existing GNOME Terminal and Ghostty tests continue to pass unchanged.

## Constraints

- Herdr 0.7.3 or newer, with `herdr api snapshot` and workspace CLI commands.
- Python 3.11+, stdlib plus existing system dependencies.
- X11, matching the project's current platform constraint.
- One dedicated top-level terminal window with the exact title `herdr`.
