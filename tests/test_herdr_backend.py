import importlib
import sys
import types
import unittest
from pathlib import Path
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

FOCUS_RESPONSE = """{
  "result": {
    "type": "workspace_info",
    "workspace": {"workspace_id": "w1", "label": "alpha"}
  }
}"""

CREATE_RESPONSE = """{
  "result": {
    "type": "workspace_created",
    "root_pane": {"pane_id": "w2:p1"}
  }
}"""

OK_RESPONSE = '{"result":{"type":"ok"}}'


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

    def test_missing_herdr_executable_during_snapshot_is_fatal(self):
        backends = load_backends()
        with patch.object(
            backends.subprocess,
            "run",
            side_effect=FileNotFoundError(2, "No such file or directory", "herdr"),
        ):
            with self.assertRaises(SystemExit) as ctx:
                backends.HerdrBackend().get_tabs()

        self.assertIn("snapshot", str(ctx.exception))
        self.assertIn("herdr", str(ctx.exception))


class HerdrActionTests(unittest.TestCase):
    def test_switch_workspace_focuses_workspace_then_dedicated_window(self):
        backends = load_backends()
        workspace = backends.HerdrWorkspaceEntry("alpha", "alpha", "w1")
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command == ["xdotool", "search", "--maxdepth", "1", "--name", "^herdr$"]:
                return result(stdout="123\n")
            return result(stdout=FOCUS_RESPONSE)

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            backends.HerdrBackend(session="work").switch_tab(workspace)

        self.assertEqual(calls[0], ["herdr", "--session", "work", "workspace", "focus", "w1"])
        self.assertEqual(
            calls[1],
            ["xdotool", "search", "--maxdepth", "1", "--name", "^herdr$"],
        )
        self.assertEqual(calls[2], ["xdotool", "windowactivate", "--sync", "123"])

    def test_switch_workspace_fails_when_window_is_missing(self):
        backends = load_backends()
        workspace = backends.HerdrWorkspaceEntry("alpha", "alpha", "w1")

        def fake_run(command, **kwargs):
            if command[0] == "herdr":
                return result(stdout=FOCUS_RESPONSE)
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
                return result(stdout=FOCUS_RESPONSE)
            if command == ["xdotool", "search", "--maxdepth", "1", "--name", "^herdr$"]:
                return result(stdout="123\n")
            return result(returncode=1, stderr="activation denied")

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            with self.assertRaises(SystemExit) as ctx:
                backends.HerdrBackend().switch_tab(workspace)

        self.assertIn("activation denied", str(ctx.exception))

    def test_switch_workspace_rejects_malformed_focus_response(self):
        backends = load_backends()
        workspace = backends.HerdrWorkspaceEntry("alpha", "alpha", "w1")

        with patch.object(
            backends.subprocess,
            "run",
            return_value=result(stdout=OK_RESPONSE),
        ):
            with self.assertRaises(SystemExit) as ctx:
                backends.HerdrBackend().switch_tab(workspace)

        self.assertIn("focus workspace", str(ctx.exception))

    def test_switch_workspace_fails_when_xdotool_is_missing(self):
        backends = load_backends()
        workspace = backends.HerdrWorkspaceEntry("alpha", "alpha", "w1")

        def fake_run(command, **kwargs):
            if command[0] == "herdr":
                return result(stdout=FOCUS_RESPONSE)
            raise FileNotFoundError(2, "No such file or directory", "xdotool")

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            with self.assertRaises(SystemExit) as ctx:
                backends.HerdrBackend().switch_tab(workspace)

        self.assertIn("focus Herdr window", str(ctx.exception))
        self.assertIn("xdotool", str(ctx.exception))

    def test_create_workspace_without_post_command(self):
        backends = load_backends()
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command[:2] == ["herdr", "workspace"]:
                return result(stdout=CREATE_RESPONSE)
            if command == ["xdotool", "search", "--maxdepth", "1", "--name", "^herdr$"]:
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
                return result(stdout=CREATE_RESPONSE)
            if command[:3] == ["herdr", "pane", "run"]:
                return result(stdout=OK_RESPONSE)
            if command == ["xdotool", "search", "--maxdepth", "1", "--name", "^herdr$"]:
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

    def test_create_workspace_does_nothing_for_whitespace_only_post_command(self):
        backends = load_backends()
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command[:2] == ["herdr", "workspace"]:
                return result(stdout=CREATE_RESPONSE)
            if command == ["xdotool", "search", "--maxdepth", "1", "--name", "^herdr$"]:
                return result(stdout="123\n")
            return result()

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            backends.HerdrBackend().open_directory(Path("/tmp/alpha"), "   ")

        self.assertFalse(any(command[:3] == ["herdr", "pane", "run"] for command in calls))

    def test_create_workspace_rejects_malformed_root_pane(self):
        backends = load_backends()
        malformed = '{"result":{"type":"workspace_created","root_pane":{"pane_id":"   "}}}'

        with patch.object(
            backends.subprocess,
            "run",
            return_value=result(stdout=malformed),
        ):
            with self.assertRaises(SystemExit) as ctx:
                backends.HerdrBackend().open_directory(Path("/tmp/alpha"))

        self.assertIn("create workspace", str(ctx.exception))

    def test_create_workspace_rejects_malformed_post_command_response(self):
        backends = load_backends()

        def fake_run(command, **kwargs):
            if command[:2] == ["herdr", "workspace"]:
                return result(stdout=CREATE_RESPONSE)
            return result(stdout=FOCUS_RESPONSE)

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            with self.assertRaises(SystemExit) as ctx:
                backends.HerdrBackend().open_directory(Path("/tmp/alpha"), "my_function")

        self.assertIn("run post command", str(ctx.exception))

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


if __name__ == "__main__":
    unittest.main()
