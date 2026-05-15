import tempfile
import unittest
from pathlib import Path

from tab_search_core import (
    DirectoryEntry,
    TabEntry,
    build_gnome_terminal_commands,
    build_terminal_launch_env,
    build_picker_entries,
    command_result_is_success,
    discover_first_level_directories,
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


if __name__ == "__main__":
    unittest.main()
