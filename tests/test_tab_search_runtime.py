import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

TAB_SEARCH_PATH = Path(__file__).resolve().parent.parent / "tab-search.py"


class OpenDirectoryTests(unittest.TestCase):
    def load_module(self):
        gi_module = types.ModuleType("gi")
        gi_module.require_version = lambda *args, **kwargs: None

        repository_module = types.ModuleType("gi.repository")
        repository_module.Atspi = object()

        with patch.dict(sys.modules, {"gi": gi_module, "gi.repository": repository_module}):
            spec = importlib.util.spec_from_file_location(
                "tab_search_runtime_module",
                str(TAB_SEARCH_PATH),
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

    def test_open_directory_uses_bash_launch_when_post_command_is_configured(self):
        module = self.load_module()
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command == ["xdotool", "search", "--class", "Gnome-terminal"]:
                return types.SimpleNamespace(returncode=0, stdout="96469002\n", stderr="")
            if command == ["xprop", "-id", "96469002", "WM_CLASS"]:
                return types.SimpleNamespace(
                    returncode=0,
                    stdout='WM_CLASS(STRING) = "gnome-terminal-server", "Gnome-terminal"\n',
                    stderr="",
                )
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(module, "get_terminal_child_environments", return_value=[]):
            with patch.object(module.subprocess, "run", side_effect=fake_run):
                module.open_directory_in_terminal(Path("/tmp/work"), "my_function")

        self.assertEqual(
            calls[0],
            [
                "gnome-terminal",
                "--",
                "bash",
                "-ic",
                "cd -- /tmp/work || exit 1; my_function; exec bash -i",
            ],
        )

    def test_get_live_dbus_window_numbers_introspects_terminal_window_node(self):
        module = self.load_module()
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return types.SimpleNamespace(
                returncode=0,
                stdout='<node><node name="2"/><node name="3"/></node>',
                stderr="",
            )

        with patch.object(module.subprocess, "run", side_effect=fake_run):
            numbers = module.get_live_dbus_window_numbers()

        self.assertEqual(numbers, [2, 3])
        self.assertEqual(
            calls[0],
            [
                "gdbus", "introspect", "--session",
                "--dest", "org.gnome.Terminal",
                "--object-path", "/org/gnome/Terminal/window",
                "--xml",
            ],
        )

    def test_get_live_dbus_window_numbers_returns_empty_on_failure(self):
        module = self.load_module()

        def fake_run(command, **kwargs):
            return types.SimpleNamespace(returncode=1, stdout="", stderr="error")

        with patch.object(module.subprocess, "run", side_effect=fake_run):
            self.assertEqual(module.get_live_dbus_window_numbers(), [])

    def test_main_skips_directory_discovery_when_config_is_missing(self):
        module = self.load_module()

        with patch.object(module, "get_tabs", return_value=[module.TabEntry("alpha", "alpha", 0, "/w/1")]):
            with patch.object(module, "load_launcher_config", return_value=None):
                with patch.object(module, "discover_first_level_directories") as discover_directories:
                    with patch.object(
                        module.subprocess,
                        "run",
                        return_value=types.SimpleNamespace(returncode=1, stdout="", stderr=""),
                    ):
                        with self.assertRaises(SystemExit):
                            module.main()

        discover_directories.assert_not_called()

    def test_main_uses_configured_roots_for_directory_discovery(self):
        module = self.load_module()
        config = module.LauncherConfig(roots=[Path("/tmp/one"), Path("/tmp/two")], post_cd_command=None)

        with patch.object(module, "get_tabs", return_value=[]):
            with patch.object(module, "load_launcher_config", return_value=config):
                discover_directories = Mock(return_value=[])
                with patch.object(module, "discover_first_level_directories", discover_directories):
                    with patch.object(
                        module.subprocess,
                        "run",
                        return_value=types.SimpleNamespace(returncode=1, stdout="", stderr=""),
                    ):
                        with self.assertRaises(SystemExit):
                            module.main()

        discover_directories.assert_called_once_with(config.roots)


if __name__ == "__main__":
    unittest.main()
