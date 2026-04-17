import argparse
import os
import subprocess
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
