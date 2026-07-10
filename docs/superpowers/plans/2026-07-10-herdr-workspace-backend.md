# Herdr Workspace Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a selectable Herdr backend that lists and focuses workspaces and creates a workspace for a selected directory.

**Architecture:** `HerdrBackend` will use Herdr's JSON-printing CLI wrappers rather than AT-SPI or the raw socket protocol. Pure response parsing remains in `tab_search_core.py`; side effects and user-facing failures remain in `terminal_backends.py`; `tab-search.py` only selects the configured backend.

**Tech Stack:** Python 3.11+ stdlib, Herdr 0.7.3+ CLI, rofi, xdotool, unittest.

## Global Constraints

- Herdr 0.7.3 or newer, with `herdr api snapshot` and workspace CLI commands.
- Python 3.11+, stdlib plus existing system dependencies; add no Python dependencies.
- X11, matching the project's current platform constraint.
- One dedicated top-level terminal window with the exact title `herdr`.
- Target Herdr workspaces, not Herdr tabs or panes.
- Do not start a missing default or named Herdr session.
- Preserve GNOME Terminal and Ghostty behavior unchanged.
- Spec: `docs/superpowers/specs/2026-07-10-herdr-workspace-backend-design.md`.

---

### Task 1: Herdr Configuration

**Files:**
- Modify: `tab_search_core.py:37-46,99-115`
- Test: `tests/test_tab_search_core.py:374-499`

**Interfaces:**
- Produces: `LauncherConfig.herdr_session: str | None`
- Produces: `SUPPORTED_TERMINALS` containing `"herdr"`
- Validation: `herdr_session` is absent or a non-whitespace string; accepted values are stripped.

- [ ] **Step 1: Write failing configuration tests**

Add these methods to `ConfigTests` in `tests/test_tab_search_core.py`:

```python
    def test_terminal_accepts_herdr_with_default_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text('terminal = "herdr"\n', encoding="utf-8")

            config = load_launcher_config(config_path)

        self.assertEqual(config.terminal, "herdr")
        self.assertIsNone(config.herdr_session)

    def test_herdr_session_reads_named_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(
                'terminal = "herdr"\nherdr_session = " work "\n',
                encoding="utf-8",
            )

            config = load_launcher_config(config_path)

        self.assertEqual(config.herdr_session, "work")

    def test_herdr_session_rejects_non_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text('terminal = "herdr"\nherdr_session = 3\n', encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_launcher_config(config_path)

    def test_herdr_session_rejects_blank_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(
                'terminal = "herdr"\nherdr_session = "   "\n',
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_launcher_config(config_path)
```

Extend `test_terminal_rejects_unknown_value` with:

```python
        self.assertIn("herdr", str(ctx.exception))
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python -m unittest tests.test_tab_search_core.ConfigTests -v
```

Expected: failures because `herdr` is unsupported and `LauncherConfig` has no `herdr_session`.

- [ ] **Step 3: Implement minimal configuration support**

Change the constants and dataclass in `tab_search_core.py`:

```python
SUPPORTED_TERMINALS = ("gnome-terminal", "ghostty", "herdr")


@dataclass(frozen=True)
class LauncherConfig:
    roots: list[Path]
    post_cd_command: str | None = None
    terminal: str = "gnome-terminal"
    ghostty_command: str = "ghostty"
    herdr_session: str | None = None
```

After `ghostty_command` validation in `load_launcher_config()`, add:

```python
    herdr_session = data.get("herdr_session")
    if herdr_session is not None:
        if not isinstance(herdr_session, str) or not herdr_session.strip():
            raise ConfigError("Config 'herdr_session' must be a non-empty string.")
        herdr_session = herdr_session.strip()
```

Include it in the return value:

```python
    return LauncherConfig(
        roots=roots,
        post_cd_command=post_cd_command,
        terminal=terminal,
        ghostty_command=ghostty_command,
        herdr_session=herdr_session,
    )
```

- [ ] **Step 4: Run configuration tests**

Run:

```bash
python -m unittest tests.test_tab_search_core.ConfigTests -v
```

Expected: all `ConfigTests` pass.

- [ ] **Step 5: Commit the configuration change**

```bash
git add tab_search_core.py tests/test_tab_search_core.py
git commit -m "Add Herdr backend configuration"
```

---

### Task 2: Pure Herdr Response Parsing

**Files:**
- Modify: `tab_search_core.py:15-46`
- Test: `tests/test_tab_search_core.py`

**Interfaces:**
- Produces: `HerdrWorkspaceEntry(display_name: str, raw_name: str, workspace_id: str)`
- Produces: `parse_herdr_snapshot(output: str) -> list[HerdrWorkspaceEntry]`
- Produces: `parse_herdr_workspace_created(output: str) -> str`
- Error contract: malformed JSON or response shapes raise `ValueError`.

- [ ] **Step 1: Add failing parser tests**

Add these imports in `tests/test_tab_search_core.py`:

```python
    HerdrWorkspaceEntry,
    parse_herdr_snapshot,
    parse_herdr_workspace_created,
```

Add this test class before `ConfigTests`:

```python
class HerdrResponseTests(unittest.TestCase):
    def test_snapshot_uses_worktree_checkout_path_for_dedupe(self):
        output = """{
          "result": {
            "type": "session_snapshot",
            "snapshot": {
              "workspaces": [{
                "workspace_id": "w1",
                "label": "API work",
                "worktree": {"checkout_path": "/tmp/checkouts/api-branch"}
              }],
              "panes": [{"workspace_id": "w1", "cwd": "/tmp/original"}]
            }
          }
        }"""

        self.assertEqual(
            parse_herdr_snapshot(output),
            [HerdrWorkspaceEntry("API work", "api-branch", "w1")],
        )

    def test_snapshot_falls_back_to_first_pane_cwd_then_label(self):
        output = """{
          "result": {
            "type": "session_snapshot",
            "snapshot": {
              "workspaces": [
                {"workspace_id": "w1", "label": "Renamed"},
                {"workspace_id": "w2", "label": "Label fallback"}
              ],
              "panes": [
                {"workspace_id": "w1", "cwd": "/tmp/first"},
                {"workspace_id": "w1", "cwd": "/tmp/second"},
                {"workspace_id": "w2", "cwd": null}
              ]
            }
          }
        }"""

        self.assertEqual(
            parse_herdr_snapshot(output),
            [
                HerdrWorkspaceEntry("Renamed", "first", "w1"),
                HerdrWorkspaceEntry("Label fallback", "Label fallback", "w2"),
            ],
        )

    def test_snapshot_rejects_malformed_response(self):
        for output in ("not json", '{"result":{"type":"ok"}}'):
            with self.subTest(output=output):
                with self.assertRaises(ValueError):
                    parse_herdr_snapshot(output)

    def test_workspace_created_returns_root_pane_id(self):
        output = """{
          "result": {
            "type": "workspace_created",
            "root_pane": {"pane_id": "w2:p1"}
          }
        }"""

        self.assertEqual(parse_herdr_workspace_created(output), "w2:p1")

    def test_workspace_created_rejects_missing_root_pane(self):
        with self.assertRaises(ValueError):
            parse_herdr_workspace_created('{"result":{"type":"workspace_created"}}')
```

- [ ] **Step 2: Run parser tests and verify they fail**

Run:

```bash
python -m unittest tests.test_tab_search_core.HerdrResponseTests -v
```

Expected: import failure because the dataclass and parser functions do not exist.

- [ ] **Step 3: Implement the pure parsers**

Add this dataclass near the existing entry dataclasses in `tab_search_core.py`:

```python
@dataclass(frozen=True)
class HerdrWorkspaceEntry:
    display_name: str
    raw_name: str
    workspace_id: str
```

Add these functions after `load_launcher_config()`:

```python
def _parse_herdr_result(output: str, expected_type: str) -> dict:
    try:
        payload = json.loads(output)
        result = payload["result"]
        if not isinstance(result, dict) or result.get("type") != expected_type:
            raise ValueError(f"expected Herdr response type '{expected_type}'")
        return result
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("invalid Herdr JSON response") from exc


def parse_herdr_snapshot(output: str) -> list[HerdrWorkspaceEntry]:
    result = _parse_herdr_result(output, "session_snapshot")
    try:
        snapshot = result["snapshot"]
        workspaces = snapshot["workspaces"]
        panes = snapshot["panes"]
        if not isinstance(workspaces, list) or not isinstance(panes, list):
            raise TypeError

        entries = []
        for workspace in workspaces:
            workspace_id = workspace["workspace_id"]
            label = workspace["label"]
            if not isinstance(workspace_id, str) or not isinstance(label, str):
                raise TypeError

            path = None
            worktree = workspace.get("worktree")
            if isinstance(worktree, dict):
                checkout_path = worktree.get("checkout_path")
                if isinstance(checkout_path, str) and checkout_path:
                    path = checkout_path

            if path is None:
                path = next(
                    (
                        pane.get("cwd")
                        for pane in panes
                        if isinstance(pane, dict)
                        and pane.get("workspace_id") == workspace_id
                        and isinstance(pane.get("cwd"), str)
                        and pane.get("cwd")
                    ),
                    None,
                )

            raw_name = (Path(path).name if path else "") or label
            entries.append(HerdrWorkspaceEntry(label, raw_name, workspace_id))

        return entries
    except (KeyError, TypeError) as exc:
        raise ValueError("invalid Herdr session snapshot") from exc


def parse_herdr_workspace_created(output: str) -> str:
    result = _parse_herdr_result(output, "workspace_created")
    try:
        pane_id = result["root_pane"]["pane_id"]
        if not isinstance(pane_id, str) or not pane_id:
            raise TypeError
        return pane_id
    except (KeyError, TypeError) as exc:
        raise ValueError("invalid Herdr workspace creation response") from exc
```

- [ ] **Step 4: Run parser and full core tests**

Run:

```bash
python -m unittest tests.test_tab_search_core.HerdrResponseTests -v
python -m unittest tests.test_tab_search_core -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the parser change**

```bash
git add tab_search_core.py tests/test_tab_search_core.py
git commit -m "Parse Herdr workspace responses"
```

---

### Task 3: Herdr Workspace Listing

**Files:**
- Modify: `terminal_backends.py:21-35,167-174`
- Create: `tests/test_herdr_backend.py`

**Interfaces:**
- Consumes: `parse_herdr_snapshot(output: str) -> list[HerdrWorkspaceEntry]`
- Produces: `HerdrBackend(session: str | None = None)`
- Produces: `HerdrBackend.get_tabs() -> list[HerdrWorkspaceEntry]`
- Internal: `_command(*args: str) -> list[str]` inserts `--session NAME` only for named sessions.
- Failure contract: CLI and parser failures raise `SystemExit` with operation context.

- [ ] **Step 1: Create failing backend-listing tests**

Create `tests/test_herdr_backend.py`:

```python
import importlib
import sys
import types
import unittest
from unittest.mock import patch


def load_backends():
    gi_module = types.ModuleType("gi")
    gi_module.require_version = lambda *args, **kwargs: None
    repository_module = types.ModuleType("gi.repository")
    repository_module.Atspi = object()
    with patch.dict(sys.modules, {"gi": gi_module, "gi.repository": repository_module}):
        sys.modules.pop("terminal_backends", None)
        return importlib.import_module("terminal_backends")


def result(returncode=0, stdout="", stderr=""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


SNAPSHOT = """{
  "result": {
    "type": "session_snapshot",
    "snapshot": {
      "workspaces": [{"workspace_id": "w1", "label": "alpha"}],
      "panes": [{"workspace_id": "w1", "cwd": "/tmp/alpha"}]
    }
  }
}"""


class HerdrGetTabsTests(unittest.TestCase):
    def test_default_session_uses_snapshot_cli(self):
        backends = load_backends()
        with patch.object(backends.subprocess, "run", return_value=result(stdout=SNAPSHOT)) as run:
            tabs = backends.HerdrBackend().get_tabs()

        self.assertEqual([(tab.display_name, tab.workspace_id) for tab in tabs], [("alpha", "w1")])
        run.assert_called_once_with(
            ["herdr", "api", "snapshot"],
            capture_output=True,
            text=True,
        )

    def test_named_session_inserts_global_session_argument(self):
        backends = load_backends()
        with patch.object(backends.subprocess, "run", return_value=result(stdout=SNAPSHOT)) as run:
            backends.HerdrBackend(session="work").get_tabs()

        self.assertEqual(run.call_args.args[0], ["herdr", "--session", "work", "api", "snapshot"])

    def test_stopped_server_is_fatal(self):
        backends = load_backends()
        with patch.object(
            backends.subprocess,
            "run",
            return_value=result(returncode=1, stderr="server is not running\n"),
        ):
            with self.assertRaises(SystemExit) as ctx:
                backends.HerdrBackend().get_tabs()

        self.assertIn("snapshot", str(ctx.exception))
        self.assertIn("server is not running", str(ctx.exception))

    def test_malformed_snapshot_is_fatal(self):
        backends = load_backends()
        with patch.object(backends.subprocess, "run", return_value=result(stdout="not json")):
            with self.assertRaises(SystemExit) as ctx:
                backends.HerdrBackend().get_tabs()

        self.assertIn("snapshot", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run listing tests and verify they fail**

Run:

```bash
python -m unittest tests.test_herdr_backend.HerdrGetTabsTests -v
```

Expected: failures because `HerdrBackend` does not exist.

- [ ] **Step 3: Implement command execution and workspace listing**

Add `parse_herdr_snapshot` to the imports from `tab_search_core` in `terminal_backends.py`, then add this class before `GhosttyBackend`:

```python
class HerdrBackend:
    """Herdr: JSON CLI workspace listing, focusing, and creation."""

    def __init__(self, session=None):
        self.session = session

    def _command(self, *args):
        command = ["herdr"]
        if self.session is not None:
            command.extend(["--session", self.session])
        command.extend(args)
        return command

    def _run(self, operation, *args):
        command = self._command(*args)
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            error = result.stderr.strip() or f"command failed: {' '.join(command)}"
            sys.exit(f"Herdr {operation} failed: {error}")
        return result.stdout

    def get_tabs(self):
        output = self._run("snapshot", "api", "snapshot")
        try:
            return parse_herdr_snapshot(output)
        except ValueError as exc:
            sys.exit(f"Herdr snapshot failed: {exc}")
```

- [ ] **Step 4: Run listing tests**

Run:

```bash
python -m unittest tests.test_herdr_backend.HerdrGetTabsTests -v
```

Expected: all four tests pass.

- [ ] **Step 5: Commit workspace listing**

```bash
git add terminal_backends.py tests/test_herdr_backend.py
git commit -m "List Herdr workspaces"
```

---

### Task 4: Workspace Focus And Creation

**Files:**
- Modify: `terminal_backends.py`
- Test: `tests/test_herdr_backend.py`

**Interfaces:**
- Consumes: `parse_herdr_workspace_created(output: str) -> str`
- Consumes: existing `build_cd_script(directory: Path, post_cd_command: str) -> str`
- Produces: `HerdrBackend.switch_tab(workspace: HerdrWorkspaceEntry) -> None`
- Produces: `HerdrBackend.open_directory(directory: Path, post_cd_command: str | None) -> None`
- Internal: `_focus_window() -> None` activates the first exact-title `herdr` window or raises `SystemExit`.

- [ ] **Step 1: Add failing focus and creation tests**

Append to `tests/test_herdr_backend.py`:

```python
class HerdrActionTests(unittest.TestCase):
    def test_switch_workspace_focuses_workspace_then_dedicated_window(self):
        backends = load_backends()
        workspace = backends.HerdrWorkspaceEntry("alpha", "alpha", "w1")
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command == ["xdotool", "search", "--name", "^herdr$"]:
                return result(stdout="123\n")
            return result(stdout='{"result":{"type":"ok"}}')

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            backends.HerdrBackend(session="work").switch_tab(workspace)

        self.assertEqual(calls[0], ["herdr", "--session", "work", "workspace", "focus", "w1"])
        self.assertEqual(calls[1], ["xdotool", "search", "--name", "^herdr$"])
        self.assertEqual(calls[2], ["xdotool", "windowactivate", "--sync", "123"])

    def test_switch_workspace_fails_when_window_is_missing(self):
        backends = load_backends()
        workspace = backends.HerdrWorkspaceEntry("alpha", "alpha", "w1")

        def fake_run(command, **kwargs):
            if command[0] == "herdr":
                return result(stdout='{"result":{"type":"ok"}}')
            return result(returncode=1, stderr="not found")

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            with self.assertRaises(SystemExit) as ctx:
                backends.HerdrBackend().switch_tab(workspace)

        self.assertIn("window", str(ctx.exception))

    def test_switch_workspace_fails_when_window_activation_fails(self):
        backends = load_backends()
        workspace = backends.HerdrWorkspaceEntry("alpha", "alpha", "w1")

        def fake_run(command, **kwargs):
            if command[0] == "herdr":
                return result(stdout='{"result":{"type":"ok"}}')
            if command == ["xdotool", "search", "--name", "^herdr$"]:
                return result(stdout="123\n")
            return result(returncode=1, stderr="activation denied")

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            with self.assertRaises(SystemExit) as ctx:
                backends.HerdrBackend().switch_tab(workspace)

        self.assertIn("activation denied", str(ctx.exception))

    def test_create_workspace_without_post_command(self):
        backends = load_backends()
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command[:2] == ["herdr", "workspace"]:
                return result(stdout='{"result":{"type":"workspace_created","root_pane":{"pane_id":"w2:p1"}}}')
            if command == ["xdotool", "search", "--name", "^herdr$"]:
                return result(stdout="123\n")
            return result()

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            backends.HerdrBackend().open_directory(Path("/tmp/alpha"))

        self.assertEqual(
            calls[0],
            ["herdr", "workspace", "create", "--cwd", "/tmp/alpha", "--label", "alpha", "--focus"],
        )
        self.assertFalse(any(command[:3] == ["herdr", "pane", "run"] for command in calls))

    def test_create_workspace_runs_nonblank_post_command_in_root_pane(self):
        backends = load_backends()
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command[:2] == ["herdr", "workspace"]:
                return result(stdout='{"result":{"type":"workspace_created","root_pane":{"pane_id":"w2:p1"}}}')
            if command == ["xdotool", "search", "--name", "^herdr$"]:
                return result(stdout="123\n")
            return result()

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            backends.HerdrBackend().open_directory(Path("/tmp/alpha"), "my_function")

        self.assertIn(
            [
                "herdr",
                "pane",
                "run",
                "w2:p1",
                "bash -ic 'cd -- /tmp/alpha || exit 1; my_function; exec bash -i'",
            ],
            calls,
        )

    def test_create_workspace_does_nothing_for_blank_post_command(self):
        backends = load_backends()
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command[:2] == ["herdr", "workspace"]:
                return result(stdout='{"result":{"type":"workspace_created","root_pane":{"pane_id":"w2:p1"}}}')
            if command == ["xdotool", "search", "--name", "^herdr$"]:
                return result(stdout="123\n")
            return result()

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            backends.HerdrBackend().open_directory(Path("/tmp/alpha"), "")

        self.assertFalse(any(command[:3] == ["herdr", "pane", "run"] for command in calls))

    def test_create_workspace_propagates_cli_failure(self):
        backends = load_backends()
        with patch.object(
            backends.subprocess,
            "run",
            return_value=result(returncode=1, stderr="server is not running"),
        ):
            with self.assertRaises(SystemExit) as ctx:
                backends.HerdrBackend().open_directory(Path("/tmp/alpha"))

        self.assertIn("create workspace", str(ctx.exception))
        self.assertIn("server is not running", str(ctx.exception))
```

Also add `from pathlib import Path` to the test file imports.

- [ ] **Step 2: Run action tests and verify they fail**

Run:

```bash
python -m unittest tests.test_herdr_backend.HerdrActionTests -v
```

Expected: failures because `switch_tab()`, `open_directory()`, and `_focus_window()` do not exist.

- [ ] **Step 3: Implement focus and workspace creation**

Add `import shlex` to `terminal_backends.py`. Import `HerdrWorkspaceEntry`, `build_cd_script`, and `parse_herdr_workspace_created` from `tab_search_core`, then add these methods to `HerdrBackend`:

```python
    def switch_tab(self, workspace):
        self._run("focus workspace", "workspace", "focus", workspace.workspace_id)
        self._focus_window()

    def open_directory(self, directory, post_cd_command=None):
        output = self._run(
            "create workspace",
            "workspace",
            "create",
            "--cwd",
            str(directory),
            "--label",
            directory.name,
            "--focus",
        )
        try:
            root_pane_id = parse_herdr_workspace_created(output)
        except ValueError as exc:
            sys.exit(f"Herdr create workspace failed: {exc}")

        if post_cd_command:
            script = build_cd_script(directory, post_cd_command)
            command = shlex.join(["bash", "-ic", script])
            self._run("run post command", "pane", "run", root_pane_id, command)

        self._focus_window()

    def _focus_window(self):
        search = subprocess.run(
            ["xdotool", "search", "--name", "^herdr$"],
            capture_output=True,
            text=True,
        )
        window_ids = search.stdout.splitlines() if search.returncode == 0 else []
        if not window_ids:
            sys.exit("Could not focus Herdr window: no exact-title 'herdr' window found.")

        activate = subprocess.run(
            ["xdotool", "windowactivate", "--sync", window_ids[0]],
            capture_output=True,
            text=True,
        )
        if activate.returncode != 0:
            error = activate.stderr.strip() or "xdotool windowactivate failed"
            sys.exit(f"Could not focus Herdr window: {error}")
```

- [ ] **Step 4: Run all Herdr backend tests**

Run:

```bash
python -m unittest tests.test_herdr_backend -v
```

Expected: all Herdr backend tests pass.

- [ ] **Step 5: Commit workspace actions**

```bash
git add terminal_backends.py tests/test_herdr_backend.py
git commit -m "Focus and create Herdr workspaces"
```

---

### Task 5: Runtime Selection, Documentation, And Full Verification

**Files:**
- Modify: `tab-search.py:1,14-20`
- Modify: `README.md:1-101,137-145`
- Test: `tests/test_tab_search_runtime.py:191-231`

**Interfaces:**
- Consumes: `LauncherConfig.herdr_session`
- Consumes: `HerdrBackend(session: str | None = None)`
- Produces: `create_backend(config)` returning `HerdrBackend` for `terminal == "herdr"`.

- [ ] **Step 1: Add failing backend-selection tests**

Update the import behavior indirectly through `load_modules()` as existing tests do. Add these methods to `CreateBackendTests` in `tests/test_tab_search_runtime.py`:

```python
    def test_herdr_config_uses_herdr(self):
        from tab_search_core import LauncherConfig

        backends, module = load_modules()
        config = LauncherConfig(roots=[Path("/tmp")], terminal="herdr")

        backend = module.create_backend(config)

        self.assertIsInstance(backend, backends.HerdrBackend)
        self.assertIsNone(backend.session)

    def test_herdr_backend_receives_configured_session(self):
        from tab_search_core import LauncherConfig

        backends, module = load_modules()
        config = LauncherConfig(
            roots=[Path("/tmp")],
            terminal="herdr",
            herdr_session="work",
        )

        backend = module.create_backend(config)

        self.assertEqual(backend.session, "work")
```

- [ ] **Step 2: Run selection tests and verify they fail**

Run:

```bash
python -m unittest tests.test_tab_search_runtime.CreateBackendTests -v
```

Expected: the new tests fail because `create_backend()` returns `GnomeTerminalBackend` for Herdr.

- [ ] **Step 3: Wire Herdr into runtime selection**

Update the module docstring and imports in `tab-search.py`:

```python
"""Fuzzy workspace/tab switcher and directory launcher for supported terminals."""

from terminal_backends import GhosttyBackend, GnomeTerminalBackend, HerdrBackend
```

Update `create_backend()`:

```python
def create_backend(launcher_config):
    if launcher_config is not None and launcher_config.terminal == "ghostty":
        return GhosttyBackend(ghostty_command=launcher_config.ghostty_command)
    if launcher_config is not None and launcher_config.terminal == "herdr":
        return HerdrBackend(session=launcher_config.herdr_session)
    return GnomeTerminalBackend()
```

- [ ] **Step 4: Run runtime tests**

Run:

```bash
python -m unittest tests.test_tab_search_runtime -v
```

Expected: all runtime tests pass.

- [ ] **Step 5: Document Herdr support**

Make these focused README changes:

1. Change the introduction to include Herdr workspaces alongside GNOME Terminal and Ghostty tabs.
2. Change backend-selection text to list `herdr`.
3. Add a `### Herdr backend` section documenting:

```markdown
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
```

4. Extend the config example and rules:

```toml
terminal = "herdr"       # gnome-terminal, ghostty, or herdr
herdr_session = "work"  # optional; omit for Herdr's default session
```

5. Add Herdr 0.7.3+ to Requirements and describe `terminal_backends.py` as containing all three backends.

- [ ] **Step 6: Run full verification**

Run:

```bash
python -m unittest discover -s tests -v
git diff --check
```

Expected: all tests pass on the local Python version and `git diff --check` prints no output.

- [ ] **Step 7: Perform a read-only live smoke check**

With the default Herdr session already running, run:

```bash
herdr api snapshot
xdotool search --name '^herdr$'
```

Expected: the first command returns a `session_snapshot` JSON response and the second prints at least one X11 window ID. Do not create or focus a workspace during this read-only smoke check.

- [ ] **Step 8: Commit runtime and documentation integration**

```bash
git add tab-search.py README.md tests/test_tab_search_runtime.py
git commit -m "Integrate Herdr workspace backend"
```
