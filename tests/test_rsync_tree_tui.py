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
        self.assertEqual(
            data["auto_update"],
            {
                "enabled": True,
                "skipped_version": "",
                "latest_version": "",
                "latest_checked_at": "",
                "last_prompted_version": "",
                "last_prompted_at": "",
            },
        )
        self.assertEqual(data["diff_viewers"], tui.DEFAULT_DIFF_VIEWERS)
        self.assertTrue(config_path.exists())

    def test_config_file_backfills_auto_update_defaults(self) -> None:
        config_path = Path(self.tmp.name) / "config.json"
        config_path.write_text(
            '{"version": 1, "auto_update": {"enabled": false}, "known_connections": []}'
        )

        data = tui.load_json_config(config_path)

        self.assertEqual(
            data["auto_update"],
            {
                "enabled": False,
                "skipped_version": "",
                "latest_version": "",
                "latest_checked_at": "",
                "last_prompted_version": "",
                "last_prompted_at": "",
            },
        )

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
            "RSYNC_TREE_TUI_PERMISSION_GROUP=dotenv_group\n"
        )
        os.environ["RSYNC_TREE_TUI_LOCAL_ROOT"] = "env_local"
        os.environ["RSYNC_TREE_TUI_REMOTE"] = "env@example:/data"
        os.environ["RSYNC_TREE_TUI_PERMISSION_GROUP"] = "env_group"
        args = argparse.Namespace(
            local_root=Path("cli_local"),
            remote="cli@example:/data",
            permission_group="cli_group",
            env_file=None,
            config=config_path,
        )

        config = tui.resolve_app_config(args)

        self.assertEqual(config.local_root, (Path(self.tmp.name) / "cli_local").resolve())
        self.assertEqual(config.remote_spec, "cli@example:/data")
        self.assertEqual(config.diff_viewers, tui.DEFAULT_DIFF_VIEWERS)
        self.assertEqual(config.permission_group, "cli_group")
        self.assertEqual(config.permission_group_source, "cli")

    def test_dotenv_local_root_relative_to_dotenv_parent(self) -> None:
        config_path = Path(self.tmp.name) / "config.json"
        project_dir = Path("project")
        project_dir.mkdir()
        env_file = project_dir / ".env"
        env_file.write_text(
            "RSYNC_TREE_TUI_LOCAL_ROOT=./storage\n"
            "RSYNC_TREE_TUI_REMOTE=dotenv@example:/data\n"
        )
        args = argparse.Namespace(
            local_root=None,
            remote=None,
            permission_group=None,
            env_file=env_file,
            config=config_path,
        )

        config = tui.resolve_app_config(args)

        self.assertEqual(
            config.local_root,
            (Path(self.tmp.name) / "project" / "storage").resolve(),
        )

    def test_shell_env_local_root_stays_relative_to_cwd(self) -> None:
        config_path = Path(self.tmp.name) / "config.json"
        os.environ["RSYNC_TREE_TUI_LOCAL_ROOT"] = "./storage"
        os.environ["RSYNC_TREE_TUI_REMOTE"] = "env@example:/data"
        args = argparse.Namespace(
            local_root=None,
            remote=None,
            permission_group=None,
            env_file=None,
            config=config_path,
        )

        config = tui.resolve_app_config(args)

        self.assertEqual(config.local_root, (Path(self.tmp.name) / "storage").resolve())

    def test_cli_local_root_stays_relative_to_cwd(self) -> None:
        config_path = Path(self.tmp.name) / "config.json"
        args = argparse.Namespace(
            local_root=Path("./storage"),
            remote="cli@example:/data",
            permission_group=None,
            env_file=None,
            config=config_path,
        )

        config = tui.resolve_app_config(args)

        self.assertEqual(config.local_root, (Path(self.tmp.name) / "storage").resolve())

    def test_permission_group_uses_known_connection_before_global_config(self) -> None:
        config_path = Path(self.tmp.name) / "config.json"
        data = tui.default_config_data()
        data["permission_group"] = "global_group"
        tui.save_json_config(config_path, data)
        args = argparse.Namespace(
            local_root=None,
            remote=None,
            permission_group=None,
            env_file=None,
            config=config_path,
        )

        with mock.patch(
            "rsync_tree_tui.choose_known_connection",
            return_value={
                "local_root": str(Path(self.tmp.name) / "known_local"),
                "remote": "known@example:/data",
                "permission_group": "known_group",
            },
        ):
            config = tui.resolve_app_config(args)

        self.assertEqual(config.remote_spec, "known@example:/data")
        self.assertEqual(config.permission_group, "known_group")
        self.assertEqual(config.permission_group_source, "known connection")

    def test_record_successful_connection_stores_permission_group(self) -> None:
        config_path = Path(self.tmp.name) / "config.json"
        data = tui.default_config_data()
        local_root = Path(self.tmp.name)

        tui.record_successful_connection(
            config_path,
            data,
            local_root,
            "user@example:/data",
            "shared",
        )

        self.assertEqual(data["known_connections"][0]["permission_group"], "shared")

    def test_parse_diff_viewers_accepts_string_or_list(self) -> None:
        self.assertEqual(
            tui.parse_diff_viewers({"diff_viewers": "nvim -d {local} {remote}"}),
            ["nvim -d {local} {remote}"],
        )
        self.assertEqual(
            tui.parse_diff_viewers({"diff_viewers": ["delta", "vimdiff {local} {remote}"]}),
            ["delta", "vimdiff {local} {remote}"],
        )


class AutoUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config.json"
        self.config_data = tui.default_config_data()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def remote_source(self, version: str | None) -> tui.RemoteUpdateSource:
        source_version = version or "0.2.4"
        source = f'#!/usr/bin/env python3\n__version__ = "{source_version}"\n# rsync\n'
        return tui.RemoteUpdateSource(source=source, version=version)

    def run_prompt_with_input(self, answer: str) -> None:
        self.config_data["auto_update"]["latest_version"] = "0.2.4"
        with (
            mock.patch("rsync_tree_tui.sys.stdin.isatty", return_value=True),
            mock.patch("builtins.print"),
            mock.patch("builtins.input", return_value=answer),
        ):
            tui.maybe_prompt_for_cached_auto_update(self.config_path, self.config_data)

    def test_semver_comparison_uses_numeric_segments(self) -> None:
        self.assertEqual(tui.compare_semver_versions("0.10.0", "0.2.0"), 1)
        self.assertEqual(tui.compare_semver_versions("0.2.0", "0.2.0"), 0)
        self.assertEqual(tui.compare_semver_versions("0.1.9", "0.2.0"), -1)
        self.assertIsNone(tui.compare_semver_versions("bad", "0.2.0"))

    def test_cached_auto_update_ignores_equal_or_older_remote_versions(self) -> None:
        for version in ("0.2.0", "0.1.9"):
            self.config_data["auto_update"]["latest_version"] = version
            with (
                self.subTest(version=version),
                mock.patch("rsync_tree_tui.sys.stdin.isatty", return_value=True),
                mock.patch("builtins.input", side_effect=AssertionError("no prompt")),
            ):
                tui.maybe_prompt_for_cached_auto_update(self.config_path, self.config_data)

    def test_cached_auto_update_skips_configured_version(self) -> None:
        self.config_data["auto_update"]["latest_version"] = "0.2.4"
        self.config_data["auto_update"]["skipped_version"] = "0.2.4"

        with (
            mock.patch("rsync_tree_tui.sys.stdin.isatty", return_value=True),
            mock.patch("builtins.input", side_effect=AssertionError("no prompt")),
        ):
            tui.maybe_prompt_for_cached_auto_update(self.config_path, self.config_data)

    def test_cached_auto_update_later_records_prompt_metadata(self) -> None:
        with mock.patch(
            "rsync_tree_tui.current_local_iso8601",
            return_value="2026-04-27T12:00:00+08:00",
        ):
            self.run_prompt_with_input("")

        auto_update = self.config_data["auto_update"]
        self.assertEqual(auto_update["last_prompted_version"], "0.2.4")
        self.assertEqual(auto_update["last_prompted_at"], "2026-04-27T12:00:00+08:00")
        self.assertEqual(auto_update["skipped_version"], "")

    def test_cached_auto_update_skip_records_skipped_version(self) -> None:
        self.run_prompt_with_input("s")

        self.assertEqual(self.config_data["auto_update"]["skipped_version"], "0.2.4")

    def test_cached_auto_update_disable_turns_off_checks(self) -> None:
        self.run_prompt_with_input("d")

        self.assertFalse(self.config_data["auto_update"]["enabled"])

    def test_cached_auto_update_update_downloads_payload_installs_and_exits(self) -> None:
        self.config_data["auto_update"]["latest_version"] = "0.2.4"
        with (
            mock.patch("rsync_tree_tui.sys.stdin.isatty", return_value=True),
            mock.patch("builtins.print"),
            mock.patch("builtins.input", return_value="u"),
            mock.patch("rsync_tree_tui.install_remote_update", return_value="0.2.4") as install,
        ):
            with self.assertRaises(SystemExit) as raised:
                tui.maybe_prompt_for_cached_auto_update(self.config_path, self.config_data)

        self.assertEqual(raised.exception.code, 0)
        install.assert_called_once_with("0.2.4")

    def test_cached_auto_update_payload_failure_exits_without_replacing(self) -> None:
        self.config_data["auto_update"]["latest_version"] = "0.2.4"
        with (
            mock.patch("rsync_tree_tui.sys.stdin.isatty", return_value=True),
            mock.patch("builtins.print"),
            mock.patch("builtins.input", return_value="u"),
            mock.patch("rsync_tree_tui.install_remote_update", side_effect=tui.UpdateError("bad payload")),
        ):
            with self.assertRaises(SystemExit) as raised:
                tui.maybe_prompt_for_cached_auto_update(self.config_path, self.config_data)

        self.assertEqual(raised.exception.code, 1)

    def test_background_check_records_new_remote_version(self) -> None:
        tui.save_json_config(self.config_path, self.config_data)

        with (
            mock.patch("rsync_tree_tui.sys.stdin.isatty", return_value=True),
            mock.patch("rsync_tree_tui.current_local_iso8601", return_value="2026-04-27T12:00:00+08:00"),
            mock.patch("rsync_tree_tui.download_remote_version", return_value="0.2.4"),
        ):
            tui.background_refresh_latest_version(self.config_path, self.config_data)

        data = tui.load_json_config(self.config_path)
        self.assertEqual(data["auto_update"]["latest_version"], "0.2.4")
        self.assertEqual(data["auto_update"]["latest_checked_at"], "2026-04-27T12:00:00+08:00")

    def test_background_check_treats_version_failure_as_no_update(self) -> None:
        tui.save_json_config(self.config_path, self.config_data)

        with (
            mock.patch("rsync_tree_tui.sys.stdin.isatty", return_value=True),
            mock.patch("rsync_tree_tui.download_remote_version", return_value=None),
        ):
            tui.background_refresh_latest_version(self.config_path, self.config_data)

        data = tui.load_json_config(self.config_path)
        self.assertEqual(data["auto_update"]["latest_version"], "")

    def test_auto_update_non_interactive_does_not_check_network(self) -> None:
        with (
            mock.patch("rsync_tree_tui.sys.stdin.isatty", return_value=False),
            mock.patch("rsync_tree_tui.download_remote_version") as download,
        ):
            thread = tui.start_background_auto_update_check(
                self.config_path,
                self.config_data,
            )

        self.assertIsNone(thread)
        download.assert_not_called()

    def test_download_remote_version_uses_small_version_file(self) -> None:
        class Response:
            status = 200
            reason = "OK"

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b"0.2.4\n"

        with mock.patch("rsync_tree_tui.urllib.request.urlopen", return_value=Response()) as urlopen:
            version = tui.download_remote_version()

        self.assertEqual(version, "0.2.4")
        urlopen.assert_called_once_with(
            tui.GITHUB_VERSION_URL,
            timeout=tui.AUTO_UPDATE_VERSION_TIMEOUT,
        )

    def test_download_remote_version_invalid_payload_is_no_update(self) -> None:
        class Response:
            status = 200
            reason = "OK"

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b"\xff"

        with mock.patch("rsync_tree_tui.urllib.request.urlopen", return_value=Response()):
            self.assertIsNone(tui.download_remote_version())

    def test_download_remote_update_source_invalid_payload_raises_update_error(self) -> None:
        class Response:
            status = 200
            reason = "OK"

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b"\xff"

        with (
            mock.patch("rsync_tree_tui.urllib.request.urlopen", return_value=Response()),
            self.assertRaises(tui.UpdateError),
        ):
            tui.download_remote_update_source()

    def test_install_remote_update_rejects_payload_version_mismatch(self) -> None:
        with (
            mock.patch(
                "rsync_tree_tui.download_remote_update_source",
                return_value=self.remote_source("0.2.5"),
            ),
            mock.patch("rsync_tree_tui.install_update_source") as install,
            self.assertRaises(tui.UpdateError),
        ):
            tui.install_remote_update("0.2.4")

        install.assert_not_called()


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

    def test_build_rsync_command_adds_whole_file_only_when_requested(self) -> None:
        whole_file_cmd = tui.build_rsync_command(
            Path("/tmp/list"),
            "/src/",
            "/dst/",
            "ssh",
            False,
            whole_file=True,
        )
        default_cmd = tui.build_rsync_command(
            Path("/tmp/list"),
            "/src/",
            "/dst/",
            "ssh",
            False,
        )

        self.assertIn("--whole-file", whole_file_cmd)
        self.assertNotIn("--whole-file", default_cmd)


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

    def test_remote_file_permission_badge_uses_file_rules(self) -> None:
        entry = tui.EntryMeta(
            rel_path="asset.bin",
            entry_type=tui.EntryType.FILE,
            size=1,
            mtime_s=1,
            perms=0o664,
        )

        self.assertEqual(tui.remote_permission_badge(entry), "[pub]")
        self.assertEqual(tui.badge_color_pair(entry), 7)

    def test_remote_directory_permission_badge_ignores_setgid(self) -> None:
        entry = tui.EntryMeta(
            rel_path="dataset",
            entry_type=tui.EntryType.DIRECTORY,
            size=0,
            mtime_s=1,
            perms=0o2755,
        )

        self.assertEqual(tui.remote_permission_badge(entry), "[rdo]")
        self.assertEqual(tui.badge_color_pair(entry), 8)

    def test_remote_nonstandard_permission_uses_numeric_badge(self) -> None:
        entry = tui.EntryMeta(
            rel_path="asset.bin",
            entry_type=tui.EntryType.FILE,
            size=1,
            mtime_s=1,
            perms=0o640,
        )

        self.assertEqual(tui.remote_permission_badge(entry), "[640]")
        self.assertEqual(tui.badge_color_pair(entry), 9)

    def test_remote_pvt_badge_uses_private_color_pair(self) -> None:
        entry = tui.EntryMeta(
            rel_path="secret",
            entry_type=tui.EntryType.DIRECTORY,
            size=0,
            mtime_s=1,
            perms=0o700,
        )

        self.assertEqual(tui.remote_permission_badge(entry), "[pvt]")
        self.assertEqual(tui.badge_color_pair(entry), 6)

    def test_render_draws_remote_badge_in_middle_column_with_badge_color(self) -> None:
        app = tui.SyncApp.__new__(tui.SyncApp)
        root = tui.TreeNode(name="", rel_path="", is_expanded=True)
        remote_file = tui.TreeNode(
            name="asset.bin",
            rel_path="asset.bin",
            parent=root,
            right_entry=tui.EntryMeta(
                rel_path="asset.bin",
                entry_type=tui.EntryType.FILE,
                size=1,
                mtime_s=1,
                perms=0o664,
            ),
        )
        root.children = {"asset.bin": remote_file}
        app.root_node = root
        app.local_root = Path("/local")
        app.remote_spec = "host:/remote"
        app.cursor_index = 0
        app.scroll_offset = 0
        app.message = ""
        app.pending_action = None
        app.pending_permission = None
        app.footer_shortcut_hits = []
        app.pagination_size = tui.DEFAULT_PAGINATION_SIZE
        app.last_cursor_rel_path = ""
        app.stdscr = mock.Mock()
        app.stdscr.getmaxyx.return_value = (24, 100)

        with (
            mock.patch("rsync_tree_tui.curses.color_pair", side_effect=lambda n: n * 100),
            mock.patch("rsync_tree_tui.curses.A_REVERSE", 0),
        ):
            app.render()

        calls = app.stdscr.addnstr.call_args_list
        self.assertTrue(
            any(
                call.args[2] == " [pub] " and call.args[4] == 700
                for call in calls
            )
        )


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

    def test_popup_only_esc_closes(self) -> None:
        app = self.make_app()
        app.render = mock.Mock()
        app.stdscr = mock.Mock()
        app.stdscr.getmaxyx.return_value = (24, 100)
        app.stdscr.getch.side_effect = [ord("q"), ord("\n"), 27]
        win = mock.Mock()

        with (
            mock.patch("rsync_tree_tui.curses.newwin", return_value=win),
            mock.patch("rsync_tree_tui.curses.color_pair", side_effect=lambda n: n),
        ):
            app._show_popup("Help", ["line"])

        self.assertEqual(app.stdscr.getch.call_count, 3)

    def test_popup_ignores_ctrl_c_interrupt_flag(self) -> None:
        app = self.make_app()
        app._interrupt_requested = True
        app.render = mock.Mock()
        app.stdscr = mock.Mock()
        app.stdscr.getmaxyx.return_value = (24, 100)
        app.stdscr.getch.side_effect = [27]
        win = mock.Mock()

        with (
            mock.patch("rsync_tree_tui.curses.newwin", return_value=win),
            mock.patch("rsync_tree_tui.curses.color_pair", side_effect=lambda n: n),
        ):
            app._show_popup("Help", ["line"])

        self.assertFalse(app._interrupt_requested)


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
            app._render_footer_shortcuts(y=20, width=160)

        calls = app.stdscr.addnstr.call_args_list
        self.assertEqual(calls[0].args, (20, 0, "Up/Down", 159, 300))
        self.assertEqual(calls[1].args, (20, 7, " Move", 152, tui.curses.A_NORMAL))
        hit_keys = {hit.key for hit in app.footer_shortcut_hits}
        self.assertIn(ord(" "), hit_keys)
        self.assertIn(ord("?"), hit_keys)
        self.assertIn(ord("f"), hit_keys)
        self.assertIn(ord("p"), hit_keys)
        self.assertNotIn(ord("F"), hit_keys)
        self.assertNotIn(ord("P"), hit_keys)
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


class CheckActionTests(unittest.TestCase):
    def make_app(self) -> tui.SyncApp:
        app = tui.SyncApp.__new__(tui.SyncApp)
        root = tui.TreeNode(name="", rel_path="", is_expanded=True)
        selected = tui.TreeNode(
            name="dataset",
            rel_path="dataset",
            parent=root,
            is_selected=True,
            left_entry=tui.EntryMeta(
                rel_path="dataset",
                entry_type=tui.EntryType.DIRECTORY,
                size=0,
                mtime_s=1,
                perms=0o755,
            ),
            right_entry=tui.EntryMeta(
                rel_path="dataset",
                entry_type=tui.EntryType.DIRECTORY,
                size=0,
                mtime_s=1,
                perms=0o755,
            ),
        )
        root.children = {"dataset": selected}
        app.root_node = root
        app.cursor_index = 0
        app.scroll_offset = 0
        app.message = ""
        app.pending_action = None
        app.pending_permission = None
        app.footer_shortcut_hits = []
        app.pagination_size = tui.DEFAULT_PAGINATION_SIZE
        return app

    def test_check_confirmation_collects_options_and_blocks_other_keys(self) -> None:
        app = self.make_app()

        app.handle_key(ord("c"))

        self.assertEqual(app.pending_action, "check")
        self.assertTrue(app.pending_check_ignore_metadata)
        self.assertEqual(app.pending_check_stop_depth_text, "")

        app.handle_key(ord("1"))
        app.handle_key(ord("2"))
        app.handle_key(127)
        app.handle_key(ord("m"))
        app.handle_key(ord("q"))

        self.assertEqual(app.pending_action, "check")
        self.assertFalse(app.pending_check_ignore_metadata)
        self.assertEqual(app.pending_check_stop_depth_text, "1")

    def test_check_help_preserves_pending_options(self) -> None:
        app = self.make_app()
        app._show_popup = mock.Mock()

        app.handle_key(ord("c"))
        app.handle_key(ord("3"))
        app.handle_key(ord("m"))
        app.handle_key(ord("?"))

        app._show_popup.assert_called_once()
        self.assertEqual(app.pending_action, "check")
        self.assertFalse(app.pending_check_ignore_metadata)
        self.assertEqual(app.pending_check_stop_depth_text, "3")

    def test_check_with_metadata_enabled_does_not_checksum_mtime_only_diff(self) -> None:
        app = tui.SyncApp.__new__(tui.SyncApp)
        root = tui.TreeNode(name="", rel_path="", is_expanded=True)
        changed = tui.TreeNode(
            name="asset.txt",
            rel_path="asset.txt",
            parent=root,
            is_selected=True,
            left_entry=tui.EntryMeta(
                rel_path="asset.txt",
                entry_type=tui.EntryType.FILE,
                size=10,
                mtime_s=1,
                perms=0o644,
            ),
            right_entry=tui.EntryMeta(
                rel_path="asset.txt",
                entry_type=tui.EntryType.FILE,
                size=10,
                mtime_s=2,
                perms=0o644,
            ),
            children_loaded=True,
        )
        root.children = {"asset.txt": changed}
        app.root_node = root
        app.pending_action = "check"
        app.pending_check_ignore_metadata = False
        app.pending_check_stop_depth_text = ""
        app.message = ""
        app._interrupt_requested = False
        app.render = mock.Mock()
        app._rsync_content_check = mock.Mock(return_value=0)

        app.execute_check()

        app._rsync_content_check.assert_not_called()
        self.assertTrue(tui.node_has_difference(changed))

    def test_content_check_itemizes_mtime_only_checksum_matches(self) -> None:
        app = tui.SyncApp.__new__(tui.SyncApp)
        app.local_root = Path("/local")
        app.remote_target = "host"
        app.remote_root = "/remote"
        app.message = ""
        app.render = mock.Mock()
        app._ssh_opts = mock.Mock(return_value=[])
        node = tui.TreeNode(
            name="coacd.json",
            rel_path="model/usd/usd_layers/collision_ready_usd_layer/coacd/coacd.json",
            left_entry=tui.EntryMeta(
                rel_path="model/usd/usd_layers/collision_ready_usd_layer/coacd/coacd.json",
                entry_type=tui.EntryType.FILE,
                size=10,
                mtime_s=1,
                perms=0o644,
            ),
            right_entry=tui.EntryMeta(
                rel_path="model/usd/usd_layers/collision_ready_usd_layer/coacd/coacd.json",
                entry_type=tui.EntryType.FILE,
                size=10,
                mtime_s=2,
                perms=0o644,
            ),
        )
        result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=".f..t...... model/usd/usd_layers/collision_ready_usd_layer/coacd/coacd.json\n",
        )

        with mock.patch("rsync_tree_tui.subprocess.run", return_value=result) as run:
            matched = app._rsync_content_check([node])

        command = run.call_args.args[0]
        self.assertIn("-aniv", command)
        self.assertEqual(matched, 1)
        self.assertFalse(tui.node_has_difference(node))

    def test_stop_depth_skips_remaining_unit_after_diff_and_continues_next_unit(self) -> None:
        app = tui.SyncApp.__new__(tui.SyncApp)
        root = tui.TreeNode(name="", rel_path="", is_expanded=True)
        dataset = tui.TreeNode(
            name="dataset",
            rel_path="dataset",
            parent=root,
            is_selected=True,
            left_entry=tui.EntryMeta(
                rel_path="dataset",
                entry_type=tui.EntryType.DIRECTORY,
                size=0,
                mtime_s=1,
                perms=0o755,
            ),
            right_entry=tui.EntryMeta(
                rel_path="dataset",
                entry_type=tui.EntryType.DIRECTORY,
                size=0,
                mtime_s=1,
                perms=0o755,
            ),
        )
        root.children = {"dataset": dataset}
        app.root_node = root
        app.pending_action = "check"
        app.pending_check_ignore_metadata = False
        app.pending_check_stop_depth_text = "1"
        app.message = ""
        app._interrupt_requested = False
        app.render = mock.Mock()
        loaded: list[str] = []

        def entry(rel_path: str, entry_type: tui.EntryType, size: int = 0) -> tui.EntryMeta:
            return tui.EntryMeta(
                rel_path=rel_path,
                entry_type=entry_type,
                size=size,
                mtime_s=1,
                perms=0o755 if entry_type == tui.EntryType.DIRECTORY else 0o644,
            )

        def make_child(parent: tui.TreeNode, name: str, entry_type: tui.EntryType, size: int = 0) -> tui.TreeNode:
            rel_path = f"{parent.rel_path}/{name}" if parent.rel_path else name
            return tui.TreeNode(
                name=name,
                rel_path=rel_path,
                parent=parent,
                left_entry=entry(rel_path, entry_type, size),
                right_entry=entry(rel_path, entry_type, size),
                children_loaded=entry_type == tui.EntryType.FILE,
            )

        def load_children(node: tui.TreeNode, limited: bool = True) -> None:
            loaded.append(node.rel_path)
            if node.rel_path == "dataset":
                node.children = {
                    "scene_a": make_child(node, "scene_a", tui.EntryType.DIRECTORY),
                    "scene_b": make_child(node, "scene_b", tui.EntryType.DIRECTORY),
                }
            elif node.rel_path == "dataset/scene_a":
                node.children = {
                    "camera": make_child(node, "camera", tui.EntryType.DIRECTORY),
                    "labels": make_child(node, "labels", tui.EntryType.DIRECTORY),
                }
            elif node.rel_path == "dataset/scene_b":
                node.children = {
                    "deep": make_child(node, "deep", tui.EntryType.DIRECTORY),
                }
            elif node.rel_path == "dataset/scene_a/camera":
                same = make_child(node, "0001.png", tui.EntryType.FILE, size=10)
                diff = make_child(node, "0002.png", tui.EntryType.FILE, size=10)
                diff.right_entry = entry(diff.rel_path, tui.EntryType.FILE, size=11)
                node.children = {"0001.png": same, "0002.png": diff}
            elif node.rel_path == "dataset/scene_a/labels":
                self.fail("short-circuited check should not load scene_a/labels")
            elif node.rel_path == "dataset/scene_b/deep":
                node.children = {
                    "ok.txt": make_child(node, "ok.txt", tui.EntryType.FILE, size=1),
                }
            node.children_loaded = True
            tui.clear_node_caches(node, include_sorted=True)
            tui.clear_ancestor_caches(node.parent)

        app.load_children = load_children

        app.execute_check()

        scene_a = dataset.children["scene_a"]
        camera = scene_a.children["camera"]
        labels = scene_a.children["labels"]
        scene_b_deep = dataset.children["scene_b"].children["deep"]
        self.assertTrue(tui.node_has_difference(scene_a))
        self.assertTrue(tui.node_has_difference(camera))
        self.assertFalse(labels.children_loaded)
        self.assertTrue(scene_b_deep.children_loaded)

    def test_stop_depth_local_only_does_not_short_circuit_but_remote_only_does(self) -> None:
        app = tui.SyncApp.__new__(tui.SyncApp)
        root = tui.TreeNode(name="", rel_path="", is_expanded=True)
        dataset = tui.TreeNode(
            name="dataset",
            rel_path="dataset",
            parent=root,
            is_selected=True,
            left_entry=tui.EntryMeta(
                rel_path="dataset",
                entry_type=tui.EntryType.DIRECTORY,
                size=0,
                mtime_s=1,
                perms=0o755,
            ),
            right_entry=tui.EntryMeta(
                rel_path="dataset",
                entry_type=tui.EntryType.DIRECTORY,
                size=0,
                mtime_s=1,
                perms=0o755,
            ),
        )
        root.children = {"dataset": dataset}
        app.root_node = root
        app.pending_action = "check"
        app.pending_check_ignore_metadata = False
        app.pending_check_stop_depth_text = "1"
        app.message = ""
        app._interrupt_requested = False
        app.render = mock.Mock()
        loaded: list[str] = []

        def meta(rel_path: str, entry_type: tui.EntryType) -> tui.EntryMeta:
            return tui.EntryMeta(
                rel_path=rel_path,
                entry_type=entry_type,
                size=0,
                mtime_s=1,
                perms=0o755 if entry_type == tui.EntryType.DIRECTORY else 0o644,
            )

        def both_dir(parent: tui.TreeNode, name: str) -> tui.TreeNode:
            rel_path = f"{parent.rel_path}/{name}" if parent.rel_path else name
            return tui.TreeNode(
                name=name,
                rel_path=rel_path,
                parent=parent,
                left_entry=meta(rel_path, tui.EntryType.DIRECTORY),
                right_entry=meta(rel_path, tui.EntryType.DIRECTORY),
            )

        def load_children(node: tui.TreeNode, limited: bool = True) -> None:
            loaded.append(node.rel_path)
            if node.rel_path == "dataset":
                node.children = {
                    "scene_a": both_dir(node, "scene_a"),
                    "scene_b": both_dir(node, "scene_b"),
                }
            elif node.rel_path == "dataset/scene_a":
                local_rel = "dataset/scene_a/local_new"
                node.children = {
                    "local_new": tui.TreeNode(
                        name="local_new",
                        rel_path=local_rel,
                        parent=node,
                        left_entry=meta(local_rel, tui.EntryType.DIRECTORY),
                    ),
                    "shared": both_dir(node, "shared"),
                }
            elif node.rel_path == "dataset/scene_a/shared":
                node.children = {
                    "ok.txt": tui.TreeNode(
                        name="ok.txt",
                        rel_path="dataset/scene_a/shared/ok.txt",
                        parent=node,
                        left_entry=meta("dataset/scene_a/shared/ok.txt", tui.EntryType.FILE),
                        right_entry=meta("dataset/scene_a/shared/ok.txt", tui.EntryType.FILE),
                        children_loaded=True,
                    ),
                }
            elif node.rel_path == "dataset/scene_b":
                remote_rel = "dataset/scene_b/remote_new"
                node.children = {
                    "remote_new": tui.TreeNode(
                        name="remote_new",
                        rel_path=remote_rel,
                        parent=node,
                        right_entry=meta(remote_rel, tui.EntryType.DIRECTORY),
                    )
                }
            elif node.rel_path.endswith("local_new") or node.rel_path.endswith("remote_new"):
                self.fail("check should not descend into single-side directories")
            node.children_loaded = True
            tui.clear_node_caches(node, include_sorted=True)
            tui.clear_ancestor_caches(node.parent)

        app.load_children = load_children

        app.execute_check()

        self.assertIn("dataset/scene_a/shared", loaded)
        self.assertTrue(tui.node_has_difference(dataset.children["scene_b"]))
        self.assertNotIn("dataset/scene_a/local_new", loaded)
        self.assertNotIn("dataset/scene_b/remote_new", loaded)


class SyncActionTests(unittest.TestCase):
    def make_download_app(self) -> tui.SyncApp:
        app = tui.SyncApp.__new__(tui.SyncApp)
        root = tui.TreeNode(name="", rel_path="", is_expanded=True)
        remote_file = tui.TreeNode(
            name="remote.txt",
            rel_path="remote.txt",
            parent=root,
            is_selected=True,
            right_entry=tui.EntryMeta(
                rel_path="remote.txt",
                entry_type=tui.EntryType.FILE,
                size=1,
                mtime_s=1,
                perms=0o644,
            ),
            children_loaded=True,
        )
        root.children = {"remote.txt": remote_file}
        app.root_node = root
        app.pending_action = "download"
        app.local_root = Path("/local")
        app.remote_target = "host"
        app.remote_root = "/remote"
        app.message = ""
        app.render = mock.Mock()
        app.suspend_tui = mock.Mock()
        app.resume_tui = mock.Mock()
        app.refresh_manifests = mock.Mock()
        app._ssh_opts = mock.Mock(return_value=[])
        app._expand_selected_paths = mock.Mock(return_value=(["remote.txt"], {
            "remote.txt": remote_file.right_entry,
        }))
        app._split_paths_by_checksum = mock.Mock(return_value=[(True, ["remote.txt"])])
        return app

    def test_download_rsync_command_uses_whole_file(self) -> None:
        app = self.make_download_app()

        with (
            mock.patch("rsync_tree_tui.subprocess.run") as run,
            mock.patch("builtins.input"),
            mock.patch("builtins.print"),
        ):
            app.execute_pending_action()

        command = run.call_args.args[0]
        self.assertIn("--whole-file", command)
        self.assertIn("--backup", command)


class PermissionActionTests(unittest.TestCase):
    def make_app(self) -> tui.SyncApp:
        app = tui.SyncApp.__new__(tui.SyncApp)
        root = tui.TreeNode(name="", rel_path="", is_expanded=True)
        local_only = tui.TreeNode(
            name="local.txt",
            rel_path="local.txt",
            parent=root,
            is_selected=True,
            left_entry=tui.EntryMeta(
                rel_path="local.txt",
                entry_type=tui.EntryType.FILE,
                size=1,
                mtime_s=1,
                perms=0o644,
            ),
        )
        remote_file = tui.TreeNode(
            name="remote.txt",
            rel_path="remote.txt",
            parent=root,
            is_selected=True,
            right_entry=tui.EntryMeta(
                rel_path="remote.txt",
                entry_type=tui.EntryType.FILE,
                size=1,
                mtime_s=1,
                perms=0o644,
                owner="alice",
                group="shared",
            ),
        )
        root.children = {"local.txt": local_only, "remote.txt": remote_file}
        app.root_node = root
        app.node_by_rel_path = {"": root, "local.txt": local_only, "remote.txt": remote_file}
        app.pending_action = None
        app.pending_permission = None
        app.message = ""
        app.remote_user = "alice"
        app.remote_target = "host"
        app.remote_root = "/remote/root"
        app.permission_group = "shared"
        app.permission_group_source = "cli"
        app.render = mock.Mock()
        app.refresh_manifests = mock.Mock()
        app._ssh_opts = mock.Mock(return_value=[])
        return app

    def test_selected_permission_paths_skip_local_only_entries(self) -> None:
        app = self.make_app()

        self.assertEqual(app._selected_remote_permission_paths(), ["remote.txt"])

    def test_permission_owner_preflight_failure_does_not_choose_mode(self) -> None:
        app = self.make_app()

        with (
            mock.patch.object(app, "_first_remote_non_owner_path", return_value="blocked.txt"),
            mock.patch.object(app, "_choose_permission_mode") as choose_mode,
        ):
            app.start_action("permission")

        self.assertIsNone(app.pending_action)
        self.assertIn("not owner", app.message)
        choose_mode.assert_not_called()

    def test_permission_mode_selection_enters_confirmation_flow(self) -> None:
        app = self.make_app()

        with (
            mock.patch.object(app, "_first_remote_non_owner_path", return_value=None),
            mock.patch.object(app, "_choose_permission_mode", return_value="rdo"),
        ):
            app.start_action("permission")

        self.assertEqual(app.pending_action, "permission")
        self.assertIsNotNone(app.pending_permission)
        self.assertEqual(app.pending_permission.mode, "rdo")
        self.assertEqual(app.pending_permission.rel_paths, ["remote.txt"])
        self.assertIn("Press y to confirm", app.message)

    def test_permission_action_renders_status_before_owner_preflight(self) -> None:
        app = self.make_app()
        app.stdscr = mock.Mock()

        def check_status(_paths: list[str]) -> None:
            self.assertIn("Checking ownership", app.message)
            self.assertGreaterEqual(app.render.call_count, 1)
            return None

        with (
            mock.patch.object(app, "_first_remote_non_owner_path", side_effect=check_status),
            mock.patch.object(app, "_choose_permission_mode", return_value="rdo"),
        ):
            app.start_action("permission")

        self.assertEqual(app.pending_action, "permission")

    def test_permission_owner_preflight_ctrl_c_terminates_ssh_and_cancels(self) -> None:
        app = self.make_app()
        app._interrupt_requested = True
        process = mock.Mock()
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["ssh"], 0.1),
        ]
        process.returncode = -15

        with (
            mock.patch("rsync_tree_tui.subprocess.Popen", return_value=process),
            mock.patch.object(app, "_reap_interrupted_process") as reap,
            mock.patch.object(app, "_choose_permission_mode") as choose_mode,
        ):
            app.start_action("permission")

        process.terminate.assert_called_once()
        reap.assert_called_once_with(process)
        choose_mode.assert_not_called()
        self.assertIsNone(app.pending_action)
        self.assertIsNone(app.pending_permission)
        self.assertFalse(app._interrupt_requested)
        self.assertEqual(app.message, "Permission action interrupted. Press r to refresh.")

    def test_permission_confirmation_executes_remote_command_and_refreshes(self) -> None:
        app = self.make_app()
        app.pending_action = "permission"
        app.pending_permission = tui.PermissionRequest("pub", ["remote.txt"], "shared")
        process = mock.Mock()
        process.communicate.return_value = ("", "")
        process.returncode = 0

        with mock.patch("rsync_tree_tui.subprocess.Popen", return_value=process) as popen:
            app.handle_key(ord("y"))

        command = popen.call_args.args[0]
        self.assertEqual(command[:2], ["ssh", "host"])
        self.assertIn("chgrp -R shared remote.txt", command[2])
        self.assertIn("chmod ug=rwx,o=rx,g+s", command[2])
        self.assertIn("chmod ug=rw,o=r", command[2])
        app.refresh_manifests.assert_called_once_with(initial_load=False)

    def test_permission_execution_ctrl_c_terminates_ssh_and_requests_refresh(self) -> None:
        app = self.make_app()
        app.pending_action = "permission"
        app.pending_permission = tui.PermissionRequest("pub", ["remote.txt"], "shared")
        app._interrupt_requested = True
        process = mock.Mock()
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["ssh"], 0.1),
        ]
        process.returncode = -15

        with (
            mock.patch("rsync_tree_tui.subprocess.Popen", return_value=process),
            mock.patch.object(app, "_reap_interrupted_process") as reap,
        ):
            app.handle_key(ord("y"))

        process.terminate.assert_called_once()
        reap.assert_called_once_with(process)
        app.refresh_manifests.assert_not_called()
        self.assertIsNone(app.pending_action)
        self.assertIsNone(app.pending_permission)
        self.assertFalse(app._interrupt_requested)
        self.assertEqual(app.message, "Permission action interrupted. Press r to refresh.")

    def test_permission_confirmation_cancel_clears_request(self) -> None:
        app = self.make_app()
        app.pending_action = "permission"
        app.pending_permission = tui.PermissionRequest("pvt", ["remote.txt"], "")

        app.handle_key(ord("n"))

        self.assertIsNone(app.pending_action)
        self.assertIsNone(app.pending_permission)
        self.assertEqual(app.message, "Cancelled pending permission action.")

    def test_permission_mode_popup_only_esc_cancels(self) -> None:
        app = self.make_app()
        app.stdscr = mock.Mock()
        app.stdscr.getmaxyx.return_value = (24, 100)
        app.stdscr.getch.side_effect = [ord("q"), 27]
        win = mock.Mock()

        with (
            mock.patch("rsync_tree_tui.curses.newwin", return_value=win),
            mock.patch("rsync_tree_tui.curses.color_pair", side_effect=lambda n: n),
        ):
            mode = app._choose_permission_mode(1)

        self.assertIsNone(mode)
        self.assertEqual(app.stdscr.getch.call_count, 2)

    def test_permission_mode_popup_ignores_ctrl_c_interrupt_flag(self) -> None:
        app = self.make_app()
        app._interrupt_requested = True
        app.stdscr = mock.Mock()
        app.stdscr.getmaxyx.return_value = (24, 100)
        app.stdscr.getch.side_effect = [ord("1")]
        win = mock.Mock()

        with (
            mock.patch("rsync_tree_tui.curses.newwin", return_value=win),
            mock.patch("rsync_tree_tui.curses.color_pair", side_effect=lambda n: n),
        ):
            mode = app._choose_permission_mode(1)

        self.assertEqual(mode, "rdo")
        self.assertFalse(app._interrupt_requested)

    def test_permission_mode_popup_colors_configured_group_value_green(self) -> None:
        app = self.make_app()
        app.stdscr = mock.Mock()
        app.stdscr.getmaxyx.return_value = (24, 100)
        app.stdscr.getch.side_effect = [27]
        win = mock.Mock()

        with (
            mock.patch("rsync_tree_tui.curses.newwin", return_value=win),
            mock.patch("rsync_tree_tui.curses.color_pair", side_effect=lambda n: n * 100),
        ):
            app._choose_permission_mode(1)

        calls = win.addnstr.call_args_list
        self.assertTrue(
            any(call.args[2].startswith("shared (cli)") and call.args[4] == 500 for call in calls)
        )

    def test_permission_mode_popup_colors_missing_group_value_yellow(self) -> None:
        app = self.make_app()
        app.permission_group = ""
        app.permission_group_source = "none"
        app.stdscr = mock.Mock()
        app.stdscr.getmaxyx.return_value = (24, 100)
        app.stdscr.getch.side_effect = [27]
        win = mock.Mock()

        with (
            mock.patch("rsync_tree_tui.curses.newwin", return_value=win),
            mock.patch("rsync_tree_tui.curses.color_pair", side_effect=lambda n: n * 100),
        ):
            app._choose_permission_mode(1)

        calls = win.addnstr.call_args_list
        self.assertTrue(
            any(call.args[2].startswith("<none>") and call.args[4] == 300 for call in calls)
        )

    def test_diff_shortcuts_use_f_and_permission_uses_p(self) -> None:
        app = self.make_app()
        app._try_preview_diff = mock.Mock()
        app.start_action = mock.Mock()

        app.handle_key(ord("f"))
        app.handle_key(ord("F"))
        app.handle_key(ord("p"))

        app._try_preview_diff.assert_has_calls(
            [mock.call(), mock.call(external=True)]
        )
        app.start_action.assert_called_once_with("permission")


class RemotePermissionCommandTests(unittest.TestCase):
    def test_permission_command_with_group_chgrp_and_uses_shared_rules(self) -> None:
        command = tui.build_remote_permission_command(
            "/root path",
            ["dir one"],
            "rdo",
            "shared team",
        )

        self.assertIn("cd '/root path'", command)
        self.assertIn("trap 'exit 130' INT TERM HUP", command)
        self.assertIn("chgrp -R 'shared team' 'dir one'", command)
        self.assertIn("chmod u=rwx,go=rx,g+s", command)
        self.assertIn("chmod u=rw,go=r", command)

    def test_permission_command_without_group_uses_safe_public_fallback(self) -> None:
        command = tui.build_remote_permission_command(
            "/remote",
            ["staging"],
            "pub",
            "",
        )

        self.assertNotIn("chgrp", command)
        self.assertIn("chmod ug=rwx,o=rx", command)
        self.assertIn("chmod ug=rw,o=r", command)


class RemotePermissionsScriptTests(unittest.TestCase):
    def test_public_mode_allows_group_write_and_other_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "public"
            child_file = target / "data.txt"
            target.mkdir()
            child_file.write_text("shared\n")
            target.chmod(0o777)
            child_file.chmod(0o666)

            subprocess.run(
                [
                    "bash",
                    "setup_remote_permissions.sh",
                    "--group",
                    target.group(),
                    "pub",
                    str(target),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            dir_mode = target.stat().st_mode
            file_mode = child_file.stat().st_mode
            self.assertEqual(dir_mode & 0o777, 0o775)
            self.assertEqual(dir_mode & 0o2000, 0o2000)
            self.assertEqual(file_mode & 0o777, 0o664)

    def test_rdo_mode_sets_exact_read_only_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "rdo"
            child_file = target / "data.txt"
            target.mkdir()
            child_file.write_text("release\n")
            target.chmod(0o777)
            child_file.chmod(0o666)

            subprocess.run(
                [
                    "bash",
                    "setup_remote_permissions.sh",
                    "--group",
                    target.group(),
                    "rdo",
                    str(target),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            dir_mode = target.stat().st_mode
            file_mode = child_file.stat().st_mode
            self.assertEqual(dir_mode & 0o777, 0o755)
            self.assertEqual(dir_mode & 0o2000, 0o2000)
            self.assertEqual(file_mode & 0o777, 0o644)

    def test_pvt_mode_sets_exact_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "pvt"
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
                    "pvt",
                    str(target),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertEqual(target.stat().st_mode & 0o2000, 0)
            self.assertEqual(child_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(child_dir.stat().st_mode & 0o2000, 0)
            self.assertEqual(child_file.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
