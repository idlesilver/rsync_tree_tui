# Configuration

本文记录 `rsync-tree-tui` 的配置细节。快速使用见 [README](../README.md)。

## 配置来源

`local_root` 的来源优先级：

```text
--local-root > RSYNC_TREE_TUI_LOCAL_ROOT > .env > 当前工作目录
```

`remote` 的来源优先级：

```text
--remote > RSYNC_TREE_TUI_REMOTE > .env > known connection picker
```

`permission_group` 的来源优先级：

```text
--permission-group > RSYNC_TREE_TUI_PERMISSION_GROUP > .env > selected known connection > global config > 空
```

`.env` 默认从启动目录读取，也可以通过 `--env-file` 指定。`.env` 中的相对 `RSYNC_TREE_TUI_LOCAL_ROOT=./storage` 和本地 `RSYNC_TREE_TUI_REMOTE=./nas` 会相对 `.env` 所在目录解析；CLI 参数和 shell 环境变量中的相对路径仍相对启动目录解析。

## Path 解析

`local_root` 始终是本地路径，支持普通绝对/相对路径，也支持 GVFS SMB 挂载路径：

```bash
--local-root '/run/user/1000/gvfs/smb-share:server=disk.galbot.vip,share=simvla/games'
```

`remote` 可以是 SSH rsync 目标，也可以是本地路径：

```bash
--remote user@host:/data/project
--remote ssh-config-name:/data/project
--remote /mnt/nas/project
--remote './other-copy'
--remote '/run/user/1000/gvfs/smb-share:server=disk.galbot.vip,share=simvla/games'
```

判定规则：

- 以 `/`、`./`、`../`、`~` 开头的 `remote` 按本地路径处理，即使中间包含冒号。
- 不含冒号的 `remote` 按本地路径处理。
- `host:path` 这类歧义形式保持 SSH remote 语义。
- 本地 `remote` 会在 known connections 中保存为绝对路径。
- `local_root` 和本地 `remote` 相同或互相嵌套时会拒绝启动。

SSH config name 原样传给 `ssh` 和 `rsync`，因此 `HostName`、`User`、`Port`、`IdentityFile`、`ProxyJump` 等配置仍由用户的 SSH config 决定。工具只为当前进程注入自己的 ControlMaster socket，避免多个 TUI 实例互相关闭共享 socket。

## 全局配置

首次运行会创建：

```text
~/.config/rsync-tree-tui/config.json
```

配置样例见 [config.example.json](../config.example.json)。该文件维护 checksum 策略、diff viewer、file editor、image opener、mouse wheel、auto update 和成功连接过的 local/remote。没有传入 `remote` 时，工具会按访问次数列出历史连接，让用户输入 index 选择。

## Auto Update

常规启动默认会在后台用短超时读取 GitHub 上的 `VERSION` 文件。发现新版本后先记录到配置中；下次启动时如果记录的远端版本仍高于本地版本，会提示选择立即更新、稍后提醒、跳过当前版本或关闭自动检查。网络失败、非交互式输入或版本无法解析时会静默继续启动。

```json
{
  "auto_update": {
    "enabled": true,
    "latest_version": "",
    "latest_checked_at": "",
    "skipped_version": "",
    "last_prompted_version": "",
    "last_prompted_at": ""
  }
}
```

## Diff Viewer

`f` 使用内置弹窗预览 diff；`F` 使用外部工具预览 diff，默认使用 `vim -d {local} {remote}`。

`diff_viewers` 允许配置 `vim -d`、`vimdiff`、`nvim -d`，也兼容 `delta`。vim/nvim 命令使用 `{local}`、`{remote}` 接收本地文件和临时远端副本路径；`delta` 从 stdin 读取 unified diff。

```json
{
  "diff_viewers": [
    "vim -d {local} {remote}",
    "vimdiff {local} {remote}",
    "nvim -d {local} {remote}"
  ]
}
```

## File Editor 和 Image Opener

`o` 使用配置的编辑器直接打开 local 文件，编辑器退出后刷新 manifest。`O` 会先把 remote 文件拉到本地临时副本，用编辑器打开；如果临时副本有修改，会提示是否执行单文件 upload，确认后复用现有 upload/rsync 逻辑写回 remote。

默认生成的配置文件会写入 `file_editor: "vim {file}"` 和 `image_opener`。如果没有安装 `vim`，会继续按 fallback 规则选择编辑器；如果没有安装 `timg`，图片文件会 fallback 到 `file_editor`。

```json
{
  "file_editor": "vim {file}",
  "image_opener": "sh -c 'timg \"$1\" && printf \"\\nPress Ctrl+C to return to rsync-tree-tui...\\n\" && sleep 2147483647' timg-view {file}"
}
```

默认 `vim` 不可用或旧配置未配置时，优先使用 `VISUAL` / `EDITOR` 环境变量；如果只能 fallback 到系统 GUI opener（如 `xdg-open` / `open`），remote 临时副本只作为查看，不会提示上传修改。

## Mouse Wheel

鼠标滚轮默认每个上报事件移动一行，不做合并。如果某些终端或鼠标把一个滚轮刻度上报成多个同向事件，可以手动设置 `coalesce_ms` 过滤短时间重复事件；`step` 控制每个有效滚轮事件移动的行数。

```json
{
  "mouse_wheel": {
    "step": 1,
    "coalesce_ms": 0
  }
}
```

## Checksum Policy

默认 `balanced` 策略：

- 小于等于 `size_threshold_mb` 的文件使用 rsync checksum。
- `checksum_suffixes` 中列出的后缀始终使用 checksum。
- 其他大文件使用 size+mtime。
- TUI 内 `c` 检查动作默认会对 same-size/different-mtime 文件执行 checksum 内容校验，用于忽略 metadata-only 差异。

```json
{
  "checksum_policy": {
    "mode": "balanced",
    "size_threshold_mb": 512,
    "checksum_suffixes": [".json", ".yaml", ".yml", ".txt", ".py", ".sh", ".md"]
  }
}
```
