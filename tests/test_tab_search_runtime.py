import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class OpenDirectoryTests(unittest.TestCase):
    def load_module(self):
        gi_module = types.ModuleType("gi")
        gi_module.require_version = lambda *args, **kwargs: None

        repository_module = types.ModuleType("gi.repository")
        repository_module.Atspi = object()

        with patch.dict(sys.modules, {"gi": gi_module, "gi.repository": repository_module}):
            spec = importlib.util.spec_from_file_location(
                "tab_search_runtime_module",
                "/home/phil/projects/gnometerminal-tab-search/tab-search.py",
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

    def test_open_directory_focuses_terminal_after_successful_tab_launch(self):
        module = self.load_module()
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command == ["xdotool", "search", "--class", "Gnome-terminal"]:
                return types.SimpleNamespace(returncode=0, stdout="96468993\n96469002\n", stderr="")
            if command == ["xprop", "-id", "96468993", "WM_CLASS"]:
                return types.SimpleNamespace(
                    returncode=0,
                    stdout='WM_CLASS(STRING) = "gnome-terminal-server", "Gnome-terminal-server"\n',
                    stderr="",
                )
            if command == ["xprop", "-id", "96469002", "WM_CLASS"]:
                return types.SimpleNamespace(
                    returncode=0,
                    stdout='WM_CLASS(STRING) = "gnome-terminal-server", "Gnome-terminal"\n',
                    stderr="",
                )
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(module, "get_terminal_child_environments", return_value=[
            {
                "GNOME_TERMINAL_SERVICE": ":1.100",
                "GNOME_TERMINAL_SCREEN": "/org/gnome/Terminal/screen/abc",
            }
        ]):
            with patch.object(module.subprocess, "run", side_effect=fake_run):
                module.open_directory_in_terminal(Path("/tmp/work"))

        self.assertEqual(calls[0], ["gnome-terminal", "--tab", "--working-directory=/tmp/work"])
        self.assertEqual(
            calls[-1],
            ["xdotool", "windowactivate", "--sync", "96469002"],
        )


if __name__ == "__main__":
    unittest.main()
