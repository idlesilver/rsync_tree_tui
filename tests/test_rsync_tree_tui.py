import argparse
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import rsync_tree_tui as tui


class CliTests(unittest.TestCase):
    def test_version_output(self) -> None:
        result = subprocess.run(
            [sys.executable, "rsync_tree_tui.py", "--version"],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )

        self.assertIn(tui.__version__, result.stdout)


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_env = os.environ.copy()
        self.old_cwd = Path.cwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)

    def tearDown(self) -> None:
        os.chdir(self.old_cwd)
        os.environ.clear()
        os.environ.update(self.old_env)
        self.tmp.cleanup()

    def test_config_file_is_created_with_defaults(self) -> None:
        config_path = Path(self.tmp.name) / "config.json"
        data = tui.load_json_config(config_path)
        self.assertEqual(data["version"], tui.CONFIG_VERSION)
        self.assertEqual(data["diff_viewers"], tui.DEFAULT_DIFF_VIEWERS)
        self.assertTrue(config_path.exists())

    def test_connection_trigger_count_updates(self) -> None:
        config_path = Path(self.tmp.name) / "config.json"
        data = tui.default_config_data()
        local_root = Path(self.tmp.name)
        remote = "user@example:/data"

        tui.record_successful_connection(config_path, data, local_root, remote)
        tui.record_successful_connection(config_path, data, local_root, remote)

        entries = data["known_connections"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["trigger_count"], 2)

    def test_cli_overrides_env_and_dotenv(self) -> None:
        config_path = Path(self.tmp.name) / "config.json"
        Path(".env").write_text(
            "RSYNC_TREE_TUI_LOCAL_ROOT=dotenv_local\n"
            "RSYNC_TREE_TUI_REMOTE=dotenv@example:/data\n"
        )
        os.environ["RSYNC_TREE_TUI_LOCAL_ROOT"] = "env_local"
        os.environ["RSYNC_TREE_TUI_REMOTE"] = "env@example:/data"
        args = argparse.Namespace(
            local_root=Path("cli_local"),
            remote="cli@example:/data",
            env_file=None,
            config=config_path,
        )

        config = tui.resolve_app_config(args)

        self.assertEqual(config.local_root, (Path(self.tmp.name) / "cli_local").resolve())
        self.assertEqual(config.remote_spec, "cli@example:/data")
        self.assertEqual(config.diff_viewers, tui.DEFAULT_DIFF_VIEWERS)

    def test_parse_diff_viewers_accepts_string_or_list(self) -> None:
        self.assertEqual(
            tui.parse_diff_viewers({"diff_viewers": "nvim -d {local} {remote}"}),
            ["nvim -d {local} {remote}"],
        )
        self.assertEqual(
            tui.parse_diff_viewers({"diff_viewers": ["delta", "vimdiff {local} {remote}"]}),
            ["delta", "vimdiff {local} {remote}"],
        )


class KnownConnectionDisplayTests(unittest.TestCase):
    def test_remote_display_splits_user_host_and_path(self) -> None:
        self.assertEqual(
            tui.split_remote_for_display("alice@example.com:/data/assets"),
            ("alice", "example.com", ":/data/assets"),
        )

    def test_remote_display_handles_host_without_user(self) -> None:
        self.assertEqual(
            tui.split_remote_for_display("example.com:/data/assets"),
            ("", "example.com", ":/data/assets"),
        )

    def test_colored_remote_display_uses_ansi_segments(self) -> None:
        text = tui.format_remote_for_display("alice@example.com:/data", use_color=True)

        self.assertIn(tui.ANSI_GREEN, text)
        self.assertIn(tui.ANSI_CYAN, text)
        self.assertIn(tui.ANSI_YELLOW, text)

    def test_plain_remote_display_has_no_ansi_segments(self) -> None:
        text = tui.format_remote_for_display("alice@example.com:/data", use_color=False)

        self.assertEqual(text, "alice@example.com:/data")
        self.assertNotIn("\033[", text)

    def test_known_connection_entry_keeps_copyable_text_without_color(self) -> None:
        text = tui.format_known_connection_entry(
            2,
            {
                "local_root": "/local",
                "remote": "alice@example.com:/data",
                "trigger_count": 4,
            },
            use_color=False,
        )

        self.assertEqual(text, "  [2] /local  <->  alice@example.com:/data  (4 runs)")


class ManifestTests(unittest.TestCase):
    def test_manifest_parser_accepts_tab_in_path(self) -> None:
        fields = [
            "dir\tname/file.txt",
            "f",
            "12",
            "123.4",
            "644",
            "alice",
            "staff",
        ]
        output = "\0".join(fields).encode("utf-8") + b"\0"

        entries = tui.parse_manifest_output(output)

        entry = entries["dir\tname/file.txt"]
        self.assertEqual(entry.size, 12)
        self.assertEqual(entry.owner, "alice")


class ChecksumPolicyTests(unittest.TestCase):
    def test_balanced_policy_uses_suffix_and_size_threshold(self) -> None:
        policy = tui.ChecksumPolicy(
            mode="balanced",
            size_threshold_bytes=1024,
            checksum_suffixes={".json"},
        )

        self.assertTrue(policy.should_checksum("large.json", 10_000))
        self.assertTrue(policy.should_checksum("small.bin", 100))
        self.assertFalse(policy.should_checksum("large.bin", 10_000))

    def test_build_rsync_command_adds_checksum_only_when_requested(self) -> None:
        checksum_cmd = tui.build_rsync_command(
            Path("/tmp/list"),
            "/src/",
            "/dst/",
            "ssh",
            True,
        )
        quick_cmd = tui.build_rsync_command(
            Path("/tmp/list"),
            "/src/",
            "/dst/",
            "ssh",
            False,
        )

        self.assertIn("--checksum", checksum_cmd)
        self.assertNotIn("--checksum", quick_cmd)

    def test_build_rsync_command_adds_backup_only_when_requested(self) -> None:
        backup_cmd = tui.build_rsync_command(
            Path("/tmp/list"),
            "/src/",
            "/dst/",
            "ssh",
            False,
            backup=True,
        )
        default_cmd = tui.build_rsync_command(
            Path("/tmp/list"),
            "/src/",
            "/dst/",
            "ssh",
            False,
        )

        self.assertIn("--backup", backup_cmd)
        self.assertNotIn("--backup", default_cmd)


class RenderTests(unittest.TestCase):
    def test_missing_side_renders_without_placeholder_text(self) -> None:
        node = tui.TreeNode(name="asset.bin", rel_path="asset.bin")

        cell = tui.render_side_cell(node, "left", 40)

        self.assertNotIn("<missing>", cell)

    def test_error_side_keeps_error_placeholder_text(self) -> None:
        node = tui.TreeNode(
            name="asset.bin",
            rel_path="asset.bin",
            left_load_error="failed",
        )

        cell = tui.render_side_cell(node, "left", 40)

        self.assertIn("<error>", cell)


class PopupTextTests(unittest.TestCase):
    def make_app(self) -> tui.SyncApp:
        return tui.SyncApp.__new__(tui.SyncApp)

    def test_slice_popup_cells_replaces_control_chars_and_pads(self) -> None:
        app = self.make_app()

        self.assertEqual(app._slice_popup_cells("\x1b[0mabc", 0, 6), "abc   ")

    def test_slice_popup_cells_respects_horizontal_cell_offset(self) -> None:
        app = self.make_app()

        self.assertEqual(app._slice_popup_cells("abcdef", 2, 3), "cde")

    def test_slice_popup_cells_does_not_exceed_wide_char_width(self) -> None:
        app = self.make_app()

        self.assertEqual(app._text_cell_width(app._slice_popup_cells("中abc", 0, 3)), 3)


class DiffViewerTests(unittest.TestCase):
    def make_app(self) -> tui.SyncApp:
        app = tui.SyncApp.__new__(tui.SyncApp)
        app.diff_viewers = ["missing-viewer", "vim -d {local} {remote}"]
        app.message = ""
        return app

    def test_available_diff_viewer_uses_first_installed_command(self) -> None:
        app = self.make_app()

        with mock.patch(
            "rsync_tree_tui.shutil.which",
            side_effect=lambda name: f"/usr/bin/{name}" if name == "vim" else None,
        ):
            viewer = app._available_diff_viewer()

        self.assertEqual(viewer, "vim -d {local} {remote}")

    def test_available_diff_viewer_skips_unsupported_configured_commands(self) -> None:
        app = self.make_app()
        app.diff_viewers = ["less -S", "nvim -d {local} {remote}"]

        with mock.patch(
            "rsync_tree_tui.shutil.which",
            side_effect=lambda name: f"/usr/bin/{name}" if name == "nvim" else None,
        ):
            viewer = app._available_diff_viewer()

        self.assertEqual(viewer, "nvim -d {local} {remote}")

    def test_supported_external_diff_viewer_allowlist(self) -> None:
        self.assertTrue(tui.is_supported_external_diff_viewer("delta"))
        self.assertTrue(tui.is_supported_external_diff_viewer("vimdiff {local} {remote}"))
        self.assertTrue(tui.is_supported_external_diff_viewer("vim -d {local} {remote}"))
        self.assertTrue(tui.is_supported_external_diff_viewer("nvim -d {local} {remote}"))
        self.assertFalse(tui.is_supported_external_diff_viewer("less -S"))

    def test_external_diff_viewer_receives_diff_on_stdin_without_placeholders(self) -> None:
        app = self.make_app()
        app.suspend_tui = mock.Mock()
        app.resume_tui = mock.Mock()

        with mock.patch("rsync_tree_tui.subprocess.run") as run:
            handled = app._run_external_diff_viewer(
                "delta --wrap-max-lines=unlimited",
                Path("/tmp/local"),
                Path("/tmp/remote"),
                "diff text",
            )

        self.assertTrue(handled)
        run.assert_called_once_with(
            ["delta", "--wrap-max-lines=unlimited"],
            input="diff text",
            text=True,
        )
        app.suspend_tui.assert_called_once()
        app.resume_tui.assert_called_once()

    def test_external_diff_viewer_expands_local_remote_placeholders(self) -> None:
        app = self.make_app()
        app.suspend_tui = mock.Mock()
        app.resume_tui = mock.Mock()

        with mock.patch("rsync_tree_tui.subprocess.run") as run:
            handled = app._run_external_diff_viewer(
                "nvim -d {local} {remote}",
                Path("/tmp/local"),
                Path("/tmp/remote"),
                "diff text",
            )

        self.assertTrue(handled)
        run.assert_called_once_with(
            ["nvim", "-d", "/tmp/local", "/tmp/remote"],
            input=None,
            text=False,
        )


class MouseTests(unittest.TestCase):
    def make_app_with_nodes(self) -> tui.SyncApp:
        app = tui.SyncApp.__new__(tui.SyncApp)
        root = tui.TreeNode(name="", rel_path="", is_expanded=True)
        first = tui.TreeNode(
            name="first",
            rel_path="first",
            parent=root,
            left_entry=tui.EntryMeta(
                rel_path="first",
                entry_type=tui.EntryType.FILE,
                size=1,
                mtime_s=1,
                perms=0o644,
            ),
        )
        second = tui.TreeNode(
            name="second",
            rel_path="second",
            parent=root,
            left_entry=tui.EntryMeta(
                rel_path="second",
                entry_type=tui.EntryType.DIRECTORY,
                size=0,
                mtime_s=1,
                perms=0o755,
            ),
            children_loaded=True,
        )
        root.children = {"first": first, "second": second}
        app.root_node = root
        app.cursor_index = 0
        app.scroll_offset = 0
        app.last_cursor_rel_path = ""
        app.list_layout = tui.ListLayout(
            row_start=3,
            list_height=10,
            selection_width=4,
            panel_width=40,
            divider_width=3,
        )
        app.footer_shortcut_hits = []
        app.message = ""
        app.pending_action = None
        app.diff_viewers = tui.DEFAULT_DIFF_VIEWERS
        return app

    def test_list_layout_hit_test(self) -> None:
        layout = tui.ListLayout(
            row_start=3,
            list_height=5,
            selection_width=4,
            panel_width=20,
            divider_width=3,
        )

        self.assertEqual(layout.visible_index_at(4, 10, 20), 11)
        self.assertIsNone(layout.visible_index_at(2, 10, 20))
        self.assertTrue(layout.is_selection_column(3))
        self.assertFalse(layout.is_selection_column(4))

    def test_mouse_click_row_moves_cursor_without_selecting(self) -> None:
        app = self.make_app_with_nodes()

        with (
            mock.patch("rsync_tree_tui.curses.getmouse", return_value=(0, 8, 4, 0, 1)),
            mock.patch(
                "rsync_tree_tui.mouse_has_button",
                side_effect=lambda _bstate, *names: "BUTTON1_CLICKED" in names,
            ),
        ):
            app.handle_mouse_event()

        self.assertEqual(app.cursor_index, 1)
        self.assertFalse(tui.visible_nodes(app.root_node)[1].is_selected)

    def test_mouse_click_selection_column_toggles_selection(self) -> None:
        app = self.make_app_with_nodes()

        with (
            mock.patch("rsync_tree_tui.curses.getmouse", return_value=(0, 1, 4, 0, 1)),
            mock.patch(
                "rsync_tree_tui.mouse_has_button",
                side_effect=lambda _bstate, *names: "BUTTON1_CLICKED" in names,
            ),
        ):
            app.handle_mouse_event()

        self.assertEqual(app.cursor_index, 1)
        self.assertTrue(tui.visible_nodes(app.root_node)[1].is_selected)

    def test_mouse_wheel_moves_cursor(self) -> None:
        app = self.make_app_with_nodes()

        with (
            mock.patch("rsync_tree_tui.curses.getmouse", return_value=(0, 8, 4, 0, 1)),
            mock.patch(
                "rsync_tree_tui.mouse_has_button",
                side_effect=lambda _bstate, *names: "BUTTON5_PRESSED" in names,
            ),
        ):
            app.handle_mouse_event()

        self.assertEqual(app.cursor_index, 1)

    def test_mouse_motion_without_click_is_ignored(self) -> None:
        app = self.make_app_with_nodes()

        with mock.patch("rsync_tree_tui.curses.getmouse", return_value=(0, 8, 4, 0, 0)):
            app.handle_mouse_event()

        self.assertEqual(app.cursor_index, 0)

    def test_mouse_event_mask_does_not_request_motion_events(self) -> None:
        with (
            mock.patch("rsync_tree_tui.curses.BUTTON1_CLICKED", 1, create=True),
            mock.patch("rsync_tree_tui.curses.BUTTON1_PRESSED", 2, create=True),
            mock.patch("rsync_tree_tui.curses.BUTTON1_DOUBLE_CLICKED", 4, create=True),
            mock.patch("rsync_tree_tui.curses.BUTTON4_PRESSED", 8, create=True),
            mock.patch("rsync_tree_tui.curses.BUTTON5_PRESSED", 16, create=True),
            mock.patch("rsync_tree_tui.curses.REPORT_MOUSE_POSITION", 32, create=True),
        ):
            mask = tui.mouse_event_mask()

        self.assertEqual(mask, 31)

    def test_mouse_double_click_toggles_directory(self) -> None:
        app = self.make_app_with_nodes()

        with (
            mock.patch("rsync_tree_tui.curses.getmouse", return_value=(0, 8, 3, 0, 1)),
            mock.patch(
                "rsync_tree_tui.mouse_has_button",
                side_effect=lambda _bstate, *names: "BUTTON1_DOUBLE_CLICKED" in names,
            ),
        ):
            app.handle_mouse_event()

        self.assertTrue(tui.visible_nodes(app.root_node)[0].is_expanded)

    def test_deselect_all_nodes_clears_selection_cache(self) -> None:
        app = self.make_app_with_nodes()
        node = tui.visible_nodes(app.root_node)[0]
        node.is_selected = True
        self.assertEqual(tui.selection_state(node), tui.SelectionState.SELECTED)

        cleared = tui.deselect_all_nodes(app.root_node)

        self.assertEqual(cleared, 1)
        self.assertEqual(tui.selection_state(node), tui.SelectionState.UNSELECTED)

    def test_mouse_double_click_footer_shortcut_triggers_key(self) -> None:
        app = self.make_app_with_nodes()
        app.footer_shortcut_hits = [
            tui.FooterShortcutHit(y=20, start_x=5, end_x=12, key=ord(" "))
        ]

        with (
            mock.patch("rsync_tree_tui.curses.getmouse", return_value=(0, 6, 20, 0, 1)),
            mock.patch(
                "rsync_tree_tui.mouse_has_button",
                side_effect=lambda _bstate, *names: "BUTTON1_DOUBLE_CLICKED" in names,
            ),
        ):
            app.handle_mouse_event()

        self.assertTrue(tui.visible_nodes(app.root_node)[0].is_selected)

    def test_mouse_double_click_footer_clear_uses_confirmation_flow(self) -> None:
        app = self.make_app_with_nodes()
        node = tui.visible_nodes(app.root_node)[0]
        node.is_selected = True
        app.footer_shortcut_hits = [
            tui.FooterShortcutHit(y=20, start_x=5, end_x=12, key=ord("x"))
        ]

        with (
            mock.patch("rsync_tree_tui.curses.getmouse", return_value=(0, 6, 20, 0, 1)),
            mock.patch(
                "rsync_tree_tui.mouse_has_button",
                side_effect=lambda _bstate, *names: "BUTTON1_DOUBLE_CLICKED" in names,
            ),
        ):
            app.handle_mouse_event()

        self.assertEqual(app.pending_action, "clear")
        app.handle_key(ord("y"))
        self.assertFalse(node.is_selected)
        self.assertEqual(tui.selection_state(node), tui.SelectionState.UNSELECTED)

    def test_mouse_single_click_footer_shortcut_does_not_trigger_key(self) -> None:
        app = self.make_app_with_nodes()
        app.footer_shortcut_hits = [
            tui.FooterShortcutHit(y=20, start_x=5, end_x=12, key=ord(" "))
        ]

        with (
            mock.patch("rsync_tree_tui.curses.getmouse", return_value=(0, 6, 20, 0, 1)),
            mock.patch(
                "rsync_tree_tui.mouse_has_button",
                side_effect=lambda _bstate, *names: "BUTTON1_CLICKED" in names,
            ),
        ):
            app.handle_mouse_event()

        self.assertFalse(tui.visible_nodes(app.root_node)[0].is_selected)

    def test_footer_unregistered_position_does_not_trigger_key(self) -> None:
        app = self.make_app_with_nodes()
        app.footer_shortcut_hits = [
            tui.FooterShortcutHit(y=20, start_x=5, end_x=12, key=ord(" "))
        ]

        with (
            mock.patch("rsync_tree_tui.curses.getmouse", return_value=(0, 30, 20, 0, 1)),
            mock.patch(
                "rsync_tree_tui.mouse_has_button",
                side_effect=lambda _bstate, *names: "BUTTON1_DOUBLE_CLICKED" in names,
            ),
        ):
            app.handle_mouse_event()

        self.assertFalse(tui.visible_nodes(app.root_node)[0].is_selected)

    def test_footer_shortcuts_render_key_and_label_with_separate_attrs(self) -> None:
        app = self.make_app_with_nodes()
        app.stdscr = mock.Mock()

        with mock.patch("rsync_tree_tui.curses.color_pair", side_effect=lambda n: n * 100):
            app._render_footer_shortcuts(y=20, width=120)

        calls = app.stdscr.addnstr.call_args_list
        self.assertEqual(calls[0].args, (20, 0, "Up/Down", 119, 300))
        self.assertEqual(calls[1].args, (20, 7, " Move", 112, tui.curses.A_NORMAL))
        hit_keys = {hit.key for hit in app.footer_shortcut_hits}
        self.assertIn(ord(" "), hit_keys)
        self.assertIn(ord("?"), hit_keys)
        self.assertNotIn(ord("q"), hit_keys)

    def test_mouse_double_click_footer_refresh_triggers_refresh(self) -> None:
        app = self.make_app_with_nodes()
        app.footer_shortcut_hits = [
            tui.FooterShortcutHit(y=20, start_x=5, end_x=12, key=ord("r"))
        ]

        with (
            mock.patch("rsync_tree_tui.curses.getmouse", return_value=(0, 6, 20, 0, 1)),
            mock.patch(
                "rsync_tree_tui.mouse_has_button",
                side_effect=lambda _bstate, *names: "BUTTON1_DOUBLE_CLICKED" in names,
            ),
            mock.patch.object(app, "refresh_manifests") as refresh,
        ):
            app.handle_mouse_event()

        refresh.assert_called_once_with(initial_load=False)


class RemotePermissionsScriptTests(unittest.TestCase):
    def test_private_mode_removes_group_and_other_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "private"
            child_dir = target / "child"
            child_dir.mkdir(parents=True)
            child_file = child_dir / "data.txt"
            child_file.write_text("secret\n")
            target.chmod(0o777)
            child_dir.chmod(0o777)
            child_file.chmod(0o666)

            subprocess.run(
                [
                    "bash",
                    "setup_remote_permissions.sh",
                    "--group",
                    target.group(),
                    "private",
                    str(target),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            for path in (target, child_dir, child_file):
                self.assertEqual(path.stat().st_mode & 0o077, 0)


if __name__ == "__main__":
    unittest.main()
