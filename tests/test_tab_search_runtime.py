import importlib
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

TAB_SEARCH_PATH = Path(__file__).resolve().parent.parent / "tab-search.py"


def load_modules():
    """Load terminal_backends and tab-search with a faked gi package."""
    gi_module = types.ModuleType("gi")
    gi_module.require_version = lambda *args, **kwargs: None

    repository_module = types.ModuleType("gi.repository")
    repository_module.Atspi = object()

    with patch.dict(sys.modules, {"gi": gi_module, "gi.repository": repository_module}):
        sys.modules.pop("terminal_backends", None)
        backends = importlib.import_module("terminal_backends")

        spec = importlib.util.spec_from_file_location(
            "tab_search_runtime_module",
            str(TAB_SEARCH_PATH),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return backends, module


class OpenDirectoryTests(unittest.TestCase):
    def test_open_directory_focuses_terminal_after_successful_tab_launch(self):
        backends, _ = load_modules()
        backend = backends.GnomeTerminalBackend()
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

        with patch.object(backends, "get_child_environments", return_value=[
            {
                "GNOME_TERMINAL_SERVICE": ":1.100",
                "GNOME_TERMINAL_SCREEN": "/org/gnome/Terminal/screen/abc",
            }
        ]):
            with patch.object(backends.subprocess, "run", side_effect=fake_run):
                backend.open_directory(Path("/tmp/work"))

        self.assertEqual(calls[0], ["gnome-terminal", "--tab", "--working-directory=/tmp/work"])
        self.assertEqual(
            calls[-1],
            ["xdotool", "windowactivate", "--sync", "96469002"],
        )

    def test_open_directory_uses_bash_launch_when_post_command_is_configured(self):
        backends, _ = load_modules()
        backend = backends.GnomeTerminalBackend()
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

        with patch.object(backends, "get_child_environments", return_value=[]):
            with patch.object(backends.subprocess, "run", side_effect=fake_run):
                backend.open_directory(Path("/tmp/work"), "my_function")

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


class LiveWindowNumberTests(unittest.TestCase):
    def test_get_live_dbus_window_numbers_introspects_terminal_window_node(self):
        backends, _ = load_modules()
        backend = backends.GnomeTerminalBackend()
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return types.SimpleNamespace(
                returncode=0,
                stdout='<node><node name="2"/><node name="3"/></node>',
                stderr="",
            )

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            numbers = backend._get_live_dbus_window_numbers()

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
        backends, _ = load_modules()
        backend = backends.GnomeTerminalBackend()

        def fake_run(command, **kwargs):
            return types.SimpleNamespace(returncode=1, stdout="", stderr="error")

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            self.assertEqual(backend._get_live_dbus_window_numbers(), [])


class MainFlowTests(unittest.TestCase):
    def make_backend(self, tabs):
        backend = Mock()
        backend.get_tabs.return_value = tabs
        return backend

    def test_main_skips_directory_discovery_when_config_is_missing(self):
        _, module = load_modules()
        backend = self.make_backend(
            [module_tab_entry(module, "alpha")]
        )

        with patch.object(module, "create_backend", return_value=backend):
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
        _, module = load_modules()
        from tab_search_core import LauncherConfig

        config = LauncherConfig(roots=[Path("/tmp/one"), Path("/tmp/two")], post_cd_command=None)
        backend = self.make_backend([])

        with patch.object(module, "create_backend", return_value=backend):
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

    def test_main_does_not_swallow_herdr_system_exit_during_enumeration(self):
        _, module = load_modules()
        backend = self.make_backend([])
        backend.get_tabs.side_effect = SystemExit("Herdr snapshot failed: missing executable")

        with patch.object(module, "create_backend", return_value=backend):
            with patch.object(module, "load_launcher_config", return_value=None):
                with self.assertRaises(SystemExit) as ctx:
                    module.main()

        self.assertIn("Herdr snapshot failed", str(ctx.exception))


class CreateBackendTests(unittest.TestCase):
    def test_no_config_uses_gnome_terminal(self):
        backends, module = load_modules()

        backend = module.create_backend(None)

        self.assertIsInstance(backend, backends.GnomeTerminalBackend)

    def test_gnome_terminal_config_uses_gnome_terminal(self):
        from tab_search_core import LauncherConfig

        backends, module = load_modules()
        config = LauncherConfig(roots=[Path("/tmp")], terminal="gnome-terminal")

        backend = module.create_backend(config)

        self.assertIsInstance(backend, backends.GnomeTerminalBackend)

    def test_ghostty_config_uses_ghostty(self):
        from tab_search_core import LauncherConfig

        backends, module = load_modules()
        config = LauncherConfig(roots=[Path("/tmp")], terminal="ghostty")

        backend = module.create_backend(config)

        self.assertIsInstance(backend, backends.GhosttyBackend)

    def test_ghostty_backend_receives_configured_command(self):
        from tab_search_core import LauncherConfig

        backends, module = load_modules()
        config = LauncherConfig(
            roots=[Path("/tmp")],
            terminal="ghostty",
            ghostty_command="/opt/ghostty/bin/ghostty",
        )

        backend = module.create_backend(config)

        self.assertEqual(backend.ghostty_command, "/opt/ghostty/bin/ghostty")

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


def module_tab_entry(module, name):
    from tab_search_core import TabEntry

    return TabEntry(display_name=name, raw_name=name, tab_index=0, dbus_window="/w/1")


if __name__ == "__main__":
    unittest.main()
