import tempfile
import unittest
from pathlib import Path

from tab_search_core import (
    ConfigError,
    DirectoryEntry,
    LauncherConfig,
    TabEntry,
    assign_dbus_window_paths,
    build_gnome_terminal_commands,
    build_terminal_launch_env,
    build_picker_entries,
    command_result_is_success,
    discover_first_level_directories,
    load_launcher_config,
    parse_dbus_window_numbers,
    pick_focus_window_id,
    pick_remote_terminal_env,
)


class DirectoryDiscoveryTests(unittest.TestCase):
    def test_pmg_precedence_when_directory_names_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pmg = root / "pmg"
            projects = root / "projects"
            pmg.mkdir()
            projects.mkdir()

            (pmg / "shared").mkdir()
            (projects / "shared").mkdir()
            (projects / "only-projects").mkdir()

            entries = discover_first_level_directories([pmg, projects])
            by_name = {entry.name: entry for entry in entries}

            self.assertEqual(by_name["shared"].path, pmg / "shared")
            self.assertEqual(by_name["only-projects"].path, projects / "only-projects")


class PickerMergeTests(unittest.TestCase):
    def test_directory_is_omitted_when_raw_tab_name_matches(self):
        tabs = [
            TabEntry(display_name="[Window] alpha", raw_name="alpha", tab_index=0, dbus_window="/w/1"),
            TabEntry(display_name="beta", raw_name="beta", tab_index=1, dbus_window="/w/1"),
        ]
        directories = [
            DirectoryEntry(name="alpha", path=Path("/tmp/alpha")),
            DirectoryEntry(name="gamma", path=Path("/tmp/gamma")),
        ]

        entries = build_picker_entries(tabs, directories)

        self.assertEqual([entry.display_name for entry in entries], ["[Window] alpha", "beta", "gamma"])
        self.assertEqual(entries[0].kind, "tab")
        self.assertEqual(entries[2].kind, "directory-to-open")


class LaunchHelperTests(unittest.TestCase):
    def test_pick_remote_terminal_env_returns_first_complete_pair(self):
        env = pick_remote_terminal_env(
            [
                {"PATH": "/usr/bin"},
                {
                    "GNOME_TERMINAL_SERVICE": ":1.100",
                    "GNOME_TERMINAL_SCREEN": "/org/gnome/Terminal/screen/abc",
                },
                {
                    "GNOME_TERMINAL_SERVICE": ":1.101",
                    "GNOME_TERMINAL_SCREEN": "/org/gnome/Terminal/screen/def",
                },
            ]
        )

        self.assertEqual(
            env,
            {
                "GNOME_TERMINAL_SERVICE": ":1.100",
                "GNOME_TERMINAL_SCREEN": "/org/gnome/Terminal/screen/abc",
            },
        )

    def test_command_result_is_success_treats_terminal_creation_error_as_failure(self):
        self.assertFalse(
            command_result_is_success(
                returncode=0,
                stderr="# Error creating terminal: Failed to get screen from object path /org/gnome/Terminal/screen/x",
            )
        )

    def test_build_terminal_launch_env_strips_stale_terminal_vars(self):
        env = build_terminal_launch_env(
            {
                "PATH": "/usr/bin",
                "GNOME_TERMINAL_SERVICE": ":1.9",
                "GNOME_TERMINAL_SCREEN": "/org/gnome/Terminal/screen/stale",
            }
        )

        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertNotIn("GNOME_TERMINAL_SERVICE", env)
        self.assertNotIn("GNOME_TERMINAL_SCREEN", env)

    def test_build_terminal_launch_env_overlays_remote_terminal_vars(self):
        env = build_terminal_launch_env(
            {
                "PATH": "/usr/bin",
                "GNOME_TERMINAL_SERVICE": ":1.9",
                "GNOME_TERMINAL_SCREEN": "/org/gnome/Terminal/screen/stale",
            },
            {
                "GNOME_TERMINAL_SERVICE": ":1.42",
                "GNOME_TERMINAL_SCREEN": "/org/gnome/Terminal/screen/live",
            },
        )

        self.assertEqual(env["GNOME_TERMINAL_SERVICE"], ":1.42")
        self.assertEqual(env["GNOME_TERMINAL_SCREEN"], "/org/gnome/Terminal/screen/live")

    def test_build_gnome_terminal_commands_tries_tab_then_window(self):
        commands = build_gnome_terminal_commands(Path("/tmp/work"))

        self.assertEqual(
            commands,
            [
                ["gnome-terminal", "--tab", "--working-directory=/tmp/work"],
                ["gnome-terminal", "--working-directory=/tmp/work"],
            ],
        )

    def test_build_gnome_terminal_commands_with_post_command_uses_bash(self):
        commands = build_gnome_terminal_commands(Path("/tmp/work"), "my_function")

        self.assertEqual(
            commands,
            [
                [
                    "gnome-terminal",
                    "--tab",
                    "--",
                    "bash",
                    "-ic",
                    "cd -- /tmp/work || exit 1; my_function; exec bash -i",
                ],
                [
                    "gnome-terminal",
                    "--",
                    "bash",
                    "-ic",
                    "cd -- /tmp/work || exit 1; my_function; exec bash -i",
                ],
            ],
        )

    def test_pick_focus_window_id_prefers_visible_terminal_class(self):
        window_id = pick_focus_window_id(
            [
                ("96468993", 'WM_CLASS(STRING) = "gnome-terminal-server", "Gnome-terminal-server"'),
                ("96469002", 'WM_CLASS(STRING) = "gnome-terminal-server", "Gnome-terminal"'),
            ]
        )

        self.assertEqual(window_id, "96469002")


class DbusWindowMappingTests(unittest.TestCase):
    def test_parse_dbus_window_numbers_extracts_sorted_child_node_numbers(self):
        xml = (
            '<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"\n'
            '                      "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">\n'
            "<node>\n"
            '  <node name="3"/>\n'
            '  <node name="2"/>\n'
            "</node>\n"
        )

        self.assertEqual(parse_dbus_window_numbers(xml), [2, 3])

    def test_parse_dbus_window_numbers_ignores_non_numeric_nodes(self):
        xml = '<node><node name="1"/><node name="abc"/></node>'

        self.assertEqual(parse_dbus_window_numbers(xml), [1])

    def test_parse_dbus_window_numbers_handles_invalid_xml(self):
        self.assertEqual(parse_dbus_window_numbers("not xml"), [])

    def test_assign_dbus_window_paths_uses_live_window_numbers(self):
        # Window 1 was closed; the two surviving windows are 2 and 3.
        paths = assign_dbus_window_paths(2, [2, 3])

        self.assertEqual(
            paths,
            ["/org/gnome/Terminal/window/2", "/org/gnome/Terminal/window/3"],
        )

    def test_assign_dbus_window_paths_falls_back_to_sequential_on_mismatch(self):
        paths = assign_dbus_window_paths(2, [5])

        self.assertEqual(
            paths,
            ["/org/gnome/Terminal/window/1", "/org/gnome/Terminal/window/2"],
        )

    def test_assign_dbus_window_paths_falls_back_when_no_numbers_available(self):
        paths = assign_dbus_window_paths(1, [])

        self.assertEqual(paths, ["/org/gnome/Terminal/window/1"])


class ConfigTests(unittest.TestCase):
    def test_missing_config_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_launcher_config(Path(tmp) / "config.toml")

        self.assertIsNone(config)

    def test_load_launcher_config_reads_roots_and_post_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "pmg"
            second = root / "projects"
            first.mkdir()
            second.mkdir()
            config_path = root / "config.toml"
            config_path.write_text(
                f'roots = ["{first}", "{second}"]\npost_cd_command = "my_function"\n',
                encoding="utf-8",
            )

            config = load_launcher_config(config_path)

        self.assertEqual(
            config,
            LauncherConfig(
                roots=[first, second],
                post_cd_command="my_function",
            ),
        )

    def test_load_launcher_config_rejects_invalid_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text('roots = []\n', encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_launcher_config(config_path)

    def test_terminal_defaults_to_gnome_terminal_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "projects"
            root.mkdir()
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(f'roots = ["{root}"]\n', encoding="utf-8")

            config = load_launcher_config(config_path)

        self.assertEqual(config.terminal, "gnome-terminal")

    def test_terminal_accepts_ghostty(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text('terminal = "ghostty"\n', encoding="utf-8")

            config = load_launcher_config(config_path)

        self.assertEqual(config.terminal, "ghostty")

    def test_terminal_rejects_unknown_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text('terminal = "kitty"\n', encoding="utf-8")

            with self.assertRaises(ConfigError) as ctx:
                load_launcher_config(config_path)

        self.assertIn("gnome-terminal", str(ctx.exception))
        self.assertIn("ghostty", str(ctx.exception))

    def test_terminal_rejects_non_string_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text('terminal = 3\n', encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_launcher_config(config_path)

    def test_missing_roots_defaults_to_home_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text('terminal = "ghostty"\n', encoding="utf-8")

            config = load_launcher_config(config_path)

        self.assertEqual(config.roots, [Path.home()])

    def test_present_but_empty_roots_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text('terminal = "ghostty"\nroots = []\n', encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_launcher_config(config_path)


if __name__ == "__main__":
    unittest.main()
