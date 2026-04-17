# rsync-tree-tui

Single-file TUI for comparing and syncing a local tree with a remote rsync target.

## Usage

```bash
python rsync_tree_tui.py --local-root /path/to/local --remote user@host:/path/to/remote
python rsync_tree_tui.py --remote user@host:/path/to/remote
python rsync_tree_tui.py
```

Configuration priority:

1. CLI args
2. terminal environment variables
3. `.env`
4. current working directory for `local_root`
5. known connection picker for `remote`

Environment variables:

```bash
RSYNC_TREE_TUI_LOCAL_ROOT=/path/to/local
RSYNC_TREE_TUI_REMOTE=user@host:/path/to/remote
```

Global config is created at:

```text
~/.config/rsync-tree-tui/config.json
```

See `config.example.json` for the maintained shape.

## Checksum Policy

The default `balanced` policy uses rsync checksum for small files and configured
suffixes, then uses size+mtime comparison for larger files. The `c` action in
the TUI still performs checksum verification for selected same-size files.
