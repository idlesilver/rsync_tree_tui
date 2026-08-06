# Configuration

本文记录 `rsync-tree-tui` 的配置细节。快速使用见 [README](../README.md)。

## 配置来源

`local_root` 的来源优先级：

```text
--local-root > shell RSYNC_TREE_TUI_LOCAL_ROOT > .env indexed match > .env default > 当前工作目录
```

`remote` 的来源优先级：

```text
--remote > shell RSYNC_TREE_TUI_REMOTE > .env indexed match > .env default > known connection picker
```

`permission_group` 的来源优先级：

```text
--permission-group > RSYNC_TREE_TUI_PERMISSION_GROUP > .env > selected known connection > global config > 空
```

`default_upload_permission` 的来源优先级：

```text
--default-upload-permission > shell RSYNC_TREE_TUI_DEFAULT_UPLOAD_PERMISSION > .env > global config > pub-r
```

`.env` 默认从启动目录读取，也可以通过 `--env-file` 指定。`.env` 中的相对 `RSYNC_TREE_TUI_LOCAL_ROOT=./storage` 和本地 `RSYNC_TREE_TUI_REMOTE=./nas` 会相对 `.env` 所在目录解析；CLI 参数和 shell 环境变量中的相对路径仍相对启动目录解析。

## Project Remotes

旧的单值写法保持兼容：

```bash
RSYNC_TREE_TUI_REMOTE=ssh-box:/data/project
```

如果一个项目有多个 local/remote，可以使用相同编号配对：

```bash
RSYNC_TREE_TUI_LOCAL_ROOT=/workspace/default
RSYNC_TREE_TUI_REMOTE=default-box:/data/project
RSYNC_TREE_TUI_LOCAL_ROOT_0=/workspace/project-a
RSYNC_TREE_TUI_LOCAL_ROOT_1=/workspace/project-b
RSYNC_TREE_TUI_REMOTE_0=/mnt/dev-nas/project
RSYNC_TREE_TUI_REMOTE_2=archive-box:/data/project
```

没有传 `--remote` 且 shell 环境变量里没有 `RSYNC_TREE_TUI_REMOTE` 时，工具会读取 `.env` 中编号 local 和 remote 的编号并集，按 number 排序。只有一个编号连接时会直接使用；多个时会像全局 known connections 一样显示 index picker。

配对规则：

- `RSYNC_TREE_TUI_LOCAL_ROOT_<number>` 与同编号的 `RSYNC_TREE_TUI_REMOTE_<number>` 配对。
- 没有同编号 local 时，remote fallback 到默认 `RSYNC_TREE_TUI_LOCAL_ROOT`。
- 如果既没有同编号 local，也没有默认 local，则配置报错，不会静默使用当前工作目录。
- 没有同编号 remote 时，local fallback 到默认 `RSYNC_TREE_TUI_REMOTE`。
- 如果既没有同编号 remote，也没有默认 remote，则配置报错。
- 只有默认 `RSYNC_TREE_TUI_LOCAL_ROOT` 时，所有编号 remote 都使用它。
- 只有默认 `RSYNC_TREE_TUI_REMOTE` 时，所有编号 local 都使用它。
- 所有编号 remote 均有同编号 local 时，可以不配置默认 local。
- 所有编号 local 均有同编号 remote 时，可以不配置默认 remote。
- CLI 或 shell 中不带编号的 local/remote 优先级更高，会覆盖 `.env` 中对应一侧的所有编号配置。

编号 local、编号 remote 和 `.env` 默认 local/remote 中的本地相对路径都会相对 `.env` 所在目录解析。只使用不带编号配置的已有项目不会受新格式影响。

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

配置样例见 [config.example.json](../config.example.json)。该文件维护 upload 默认权限、checksum 策略、diff viewer、file editor、image opener、mouse wheel、auto update 和成功连接过的 local/remote。没有传入 `remote` 时，工具会按访问次数列出历史连接，让用户输入 index 选择。

## Upload 默认权限

`default_upload_permission` 会让 rsync 在 upload 时统一本次 file list 中条目的远端权限，默认值为 `pub-r`。

```json
{
  "default_upload_permission": "pub-r"
}
```

四层配置示例：

```bash
# .env 或 shell ENV
RSYNC_TREE_TUI_DEFAULT_UPLOAD_PERMISSION=grp-w

# CLI（最高优先级）
rsynctui --default-upload-permission pvt--
```

global config 使用上面的 JSON 写法。空字符串可以显式关闭自动权限，例如 shell 中使用 `RSYNC_TREE_TUI_DEFAULT_UPLOAD_PERMISSION=''`，或 CLI 中使用 `--default-upload-permission ''`。

支持的 badge 值及精确结果：

| 配置值 | 目录 mode | 文件 mode |
| --- | --- | --- |
| `pvt--` | `700` | `600` |
| `grp-r` | `2750` | `640` |
| `grp-w` | `2770` | `660` |
| `pub-r` | `2755` | `644` |
| `pub-w` | `2777` | `666` |

目录中的前导 `2` 是 setgid，用于让新条目继承 group。权限通过 rsync `--chmod --no-implied-dirs` 应用，只作用于显式 upload file list；远端独有的目录后代不会被递归修改，单独上传嵌套文件也不会修改其隐含父目录。项目原有的 `--keep-dirlinks` 仍然生效，因此目标端指向目录的符号链接会继续被当作目标目录使用。权限无法应用时会作为 rsync 失败处理，并沿用 rsync log 和错误摘要。

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
