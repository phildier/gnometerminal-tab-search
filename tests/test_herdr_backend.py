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
