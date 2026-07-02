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
        import importlib
        return importlib.import_module("terminal_backends")


class StubNode:
    def __init__(self, role, name="", children=None):
        self._role = role
        self._name = name
        self._children = children or []

    def get_role_name(self):
        return self._role

    def get_name(self):
        return self._name

    def get_child_count(self):
        return len(self._children)

    def get_child_at_index(self, index):
        return self._children[index]


def make_ghostty_app(frames):
    return StubNode("application", "ghostty", frames)


def make_tabbed_frame(frame_name, tab_names):
    tabs = [
        StubNode("panel", "", [StubNode("page tab", name)])
        for name in tab_names
    ]
    real_tab_list = StubNode("page tab list", "", tabs)
    # Ghostty also exposes a tab-overview "page tab list" with no page tabs.
    overview_tab_list = StubNode(
        "page tab list", "", [StubNode("panel", ""), StubNode("panel", "")]
    )
    return StubNode(
        "frame",
        frame_name,
        [
            StubNode("scroll pane", "", [overview_tab_list]),
            StubNode("scroll pane", "", [real_tab_list]),
        ],
    )


def make_tabless_frame(frame_name):
    return StubNode("frame", frame_name, [StubNode("panel", "")])


HOME = str(Path.home())


class GhosttyGetTabsTests(unittest.TestCase):
    def get_tabs(self, app, environments):
        backends = load_backends()
        backend = backends.GhosttyBackend()
        with patch.object(backend, "_find_ghostty_app", return_value=app):
            with patch.object(backends, "get_child_processes", return_value=environments):
                return backend.get_tabs()

    def test_lists_tabs_with_surface_ids(self):
        app = make_ghostty_app(
            [make_tabbed_frame("~/projects/alpha", ["~/projects/alpha", "~/pmg/beta"])]
        )
        environments = [
            ({"GHOSTTY_SURFACE_ID": "0x1"}, f"{HOME}/projects/alpha"),
            ({"GHOSTTY_SURFACE_ID": "0x2"}, f"{HOME}/pmg/beta"),
        ]

        tabs = self.get_tabs(app, environments)

        self.assertEqual(
            [(t.raw_name, t.surface_id) for t in tabs],
            [("~/projects/alpha", 0x1), ("~/pmg/beta", 0x2)],
        )

    def test_tabless_frame_yields_single_entry_named_by_frame(self):
        app = make_ghostty_app([make_tabless_frame("~/projects/alpha")])
        environments = [
            ({"GHOSTTY_SURFACE_ID": "0x1"}, f"{HOME}/projects/alpha"),
        ]

        tabs = self.get_tabs(app, environments)

        self.assertEqual([(t.raw_name, t.surface_id) for t in tabs], [("~/projects/alpha", 0x1)])

    def test_multi_window_prefixes_display_names(self):
        app = make_ghostty_app(
            [
                make_tabbed_frame("~/projects/alpha", ["~/projects/alpha"]),
                make_tabless_frame("~/pmg/beta"),
            ]
        )
        environments = [
            ({"GHOSTTY_SURFACE_ID": "0x1"}, f"{HOME}/projects/alpha"),
            ({"GHOSTTY_SURFACE_ID": "0x2"}, f"{HOME}/pmg/beta"),
        ]

        tabs = self.get_tabs(app, environments)

        self.assertEqual(
            [t.display_name for t in tabs],
            ["[~/projects/alpha] ~/projects/alpha", "[~/pmg/beta] ~/pmg/beta"],
        )

    def test_no_surface_ids_returns_empty_for_launcher_only_degradation(self):
        app = make_ghostty_app(
            [make_tabbed_frame("~/projects/alpha", ["~/projects/alpha"])]
        )
        environments = [({"PWD": f"{HOME}/projects/alpha"}, f"{HOME}/projects/alpha")]  # pre-HEAD Ghostty

        tabs = self.get_tabs(app, environments)

        self.assertEqual(tabs, [])

    def test_unmatched_tabs_are_omitted(self):
        app = make_ghostty_app(
            [make_tabbed_frame("~/projects/alpha", ["~/projects/alpha", "~/somewhere/else"])]
        )
        environments = [
            ({"GHOSTTY_SURFACE_ID": "0x1"}, f"{HOME}/projects/alpha"),
        ]

        tabs = self.get_tabs(app, environments)

        self.assertEqual([(t.raw_name, t.surface_id) for t in tabs], [("~/projects/alpha", 0x1)])

    def test_no_ghostty_app_returns_empty(self):
        tabs = self.get_tabs(None, [({"GHOSTTY_SURFACE_ID": "0x1"}, "/tmp")])

        self.assertEqual(tabs, [])


class GhosttySwitchTabTests(unittest.TestCase):
    def test_switch_tab_activates_present_surface_with_uint64_id(self):
        backends = load_backends()
        backend = backends.GhosttyBackend()
        tab = backends.GhosttyTabEntry(
            display_name="~/projects/alpha",
            raw_name="~/projects/alpha",
            surface_id=0x75BD149C639F7650,
        )
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            backend.switch_tab(tab)

        self.assertEqual(
            calls[0],
            [
                "gdbus", "call", "--session",
                "--dest", "com.mitchellh.ghostty",
                "--object-path", "/com/mitchellh/ghostty",
                "--method", "org.gtk.Actions.Activate",
                "present-surface",
                f"[<uint64 {0x75BD149C639F7650}>]",
                "{}",
            ],
        )


class GhosttyOpenDirectoryTests(unittest.TestCase):
    def test_open_directory_uses_new_window_ipc(self):
        backends = load_backends()
        backend = backends.GhosttyBackend()
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            backend.open_directory(Path("/tmp/work"))

        self.assertEqual(
            calls[0],
            ["ghostty", "+new-window", "--working-directory=/tmp/work"],
        )

    def test_open_directory_with_post_command_uses_bash(self):
        backends = load_backends()
        backend = backends.GhosttyBackend()
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            backend.open_directory(Path("/tmp/work"), "my_function")

        self.assertEqual(
            calls[0],
            [
                "ghostty",
                "+new-window",
                "-e",
                "bash",
                "-ic",
                "cd -- /tmp/work || exit 1; my_function; exec bash -i",
            ],
        )

    def test_open_directory_exits_with_stderr_on_failure(self):
        backends = load_backends()
        backend = backends.GhosttyBackend()

        def fake_run(command, **kwargs):
            return types.SimpleNamespace(returncode=1, stdout="", stderr="boom\n")

        with patch.object(backends.subprocess, "run", side_effect=fake_run):
            with self.assertRaises(SystemExit) as ctx:
                backend.open_directory(Path("/tmp/work"))

        self.assertIn("boom", str(ctx.exception))
        self.assertIn("/tmp/work", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
