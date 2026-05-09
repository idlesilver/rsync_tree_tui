# rsync-tree-tui

`rsync-tree-tui` 是一个单文件 TUI 工具，用于对比本地目录和远端 rsync 目标，并交互式选择文件或目录进行上传、下载、校验和 diff preview。

当前版本：`v0.2.8`

## 运行

```bash
python rsync_tree_tui.py --local-root /path/to/local --remote user@host:/path/to/remote
python rsync_tree_tui.py --remote user@host:/path/to/remote
python rsync_tree_tui.py
python rsync_tree_tui.py --version
python rsync_tree_tui.py --update
```

推荐设置一个本地 alias：

```bash
alias rsynctui="python /path/to/rsync_tree_tui.py"
```

依赖命令：

```text
ssh
rsync
diff
GNU find with -printf
```

## 配置优先级

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

环境变量示例：

```bash
RSYNC_TREE_TUI_LOCAL_ROOT=/path/to/local
RSYNC_TREE_TUI_REMOTE=user@host:/path/to/remote
RSYNC_TREE_TUI_PERMISSION_GROUP=asset_team
```

`.env` 默认从启动目录读取，也可以通过 `--env-file` 指定。`.env` 中的 `RSYNC_TREE_TUI_LOCAL_ROOT=./storage` 这类相对路径会相对 `.env` 所在目录解析；CLI 参数和 shell 环境变量中的相对路径仍相对启动目录解析。

## 全局配置

首次运行会创建：

```text
~/.config/rsync-tree-tui/config.json
```

该文件维护 checksum 策略和成功连接过的 local/remote。没有传入 remote 时，工具会按访问次数列出历史连接，让用户输入 index 选择。TTY 环境中，remote 的 user、host、path 会用不同颜色提示；非 TTY 或设置 `NO_COLOR` 时输出纯文本。

配置样例见 `config.example.json`。

### 自动更新检查

常规启动默认会在后台用短超时读取 GitHub 上的 `VERSION` 文件。发现新版本后先记录到配置中；下次启动时如果记录的远端版本仍高于本地版本，会提示选择立即更新、稍后提醒、跳过当前版本或关闭自动检查。网络失败、非交互式输入或版本无法解析时会静默继续启动。

可在全局配置中关闭或管理跳过版本：

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

### Diff Viewer

`f` 使用内置弹窗预览 diff；内置弹窗支持左右方向键横向移动长行。`F` 使用外部工具预览 diff，默认使用 `vim -d {local} {remote}`。

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

## 远程权限辅助脚本

TUI 中按 `p` 可以直接对选中的远端文件或目录递归应用权限模式。权限执行只修改 owner 是当前 SSH 用户的远端条目；非 owner 条目会跳过，并在前台日志中按 owner=count 汇总，便于通知同事。选择模式后仍需按 `y` 二次确认。`setup_remote_permissions.sh` 提供同样的权限规则，可作为独立远程端工具使用。

远程权限修改会像 upload/download 一样临时进入前台日志界面，实时显示阶段进度、skipped owners、warnings 和 summary；结束后按 Enter 回到 TUI。执行过程中可以用 Ctrl+C 中断；中断或 warning 后应按 `r` 刷新，重新读取远端真实权限状态。权限模式弹窗使用 Esc 取消。

权限模型分为 read、write、group 三个维度：

```text
read:   pvt / grp / any
write:  pvt / grp
group:  not change group / selected group
```

常规 `write=grp` 不会赋予 other write；`[any:g]` 表示 any readable + group writable。只有隐藏高级快捷键 `W` 可以进入 `write=any`，并且执行时需要按两次 `y` 确认。

`--permission-group` / `RSYNC_TREE_TUI_PERMISSION_GROUP` 提供一个可选 selected group；弹窗中 group 不是 `not change group` 时就会执行 `chgrp`，与 read/write 选择独立。

TUI 在 LOCAL 和 REMOTE 中间使用独立 `PERM` 列显示远端权限。按 `P` 可在 badge、owner、group、mode 视图之间切换。完整显示规则、颜色、文件/目录权限、owner/group/others 行为和修改语义见 [Permission Rules](docs/permission-rules.md)。

脚本应该在远程端运行。先把脚本复制到远程机器，再对远程目录执行 dry-run，确认后再应用：

```bash
scp setup_remote_permissions.sh user@host:/tmp/setup_remote_permissions.sh

ssh user@host 'bash /tmp/setup_remote_permissions.sh --dry-run --group asset_team grp:grp /remote/storage/staging'
ssh user@host 'bash /tmp/setup_remote_permissions.sh --group asset_team --owner chenhaozhe grp:grp /remote/storage/staging'
```

常用模式：

```bash
# 远程端：发布后的数据集只允许浏览和下载
bash /tmp/setup_remote_permissions.sh any:pvt /remote/storage/datasets/v1.0

# 远程端：开放 staging 目录，允许团队上传
bash /tmp/setup_remote_permissions.sh --group asset_team any:grp /remote/storage/datasets/staging

# 远程端：隐藏工作中目录
bash /tmp/setup_remote_permissions.sh pvt:pvt /remote/storage/wip_secret
```

脚本默认不修改 group，且只处理运行用户 owner 的条目；可以通过环境变量 `GROUP` / `OWNER` 或 `--group` / `--owner` 覆盖。需要持久化站点默认值时，直接编辑脚本开头的 `GROUP="${GROUP:-}"` 或 `OWNER="${OWNER:-$(id -un)}"`。

`pvt` 会让目标目录在父目录中仍可被看到，并显示为 `[pvt:-]`；目标目录和所有子项会移除 group/others 权限，因此其他人看不到内部文件。

## 快速上手

下面的脚本会创建两个相似但不完全相同的目录，然后用 `localhost` 作为远端目标启动工具。需要本机 SSH 可以连到 localhost。

```bash
tmp_root="$(mktemp -d)"
local_dir="$tmp_root/local"
remote_dir="$tmp_root/remote"

mkdir -p "$local_dir/sub" "$remote_dir/sub"
printf "same\n" > "$local_dir/sub/same.txt"
printf "same\n" > "$remote_dir/sub/same.txt"
printf "local only\n" > "$local_dir/local_only.txt"
printf "remote only\n" > "$remote_dir/remote_only.txt"
printf "local value\n" > "$local_dir/sub/different.txt"
printf "remote value\n" > "$remote_dir/sub/different.txt"

python rsync_tree_tui.py \
  --local-root "$local_dir" \
  --remote "localhost:$remote_dir"
```

## Checksum Policy

默认 `balanced` 策略：

- 小于等于 `size_threshold_mb` 的文件使用 rsync checksum。
- `checksum_suffixes` 中列出的后缀始终使用 checksum。
- 其他大文件使用 size+mtime。
- TUI 内 `c` 检查动作默认会对 same-size/different-mtime 文件执行 checksum 内容校验，用于忽略 metadata-only 差异。

## 同步行为

下载会使用 rsync `--backup --whole-file`。`--whole-file` 让远端覆盖本地时直接传完整文件，避免用本地旧文件作为 delta basis 时出现 verification failed。`--backup` 没有配置 `--backup-dir`，所以被覆盖的本地旧文件会保存在原文件同目录，默认文件名追加 `~` 后缀，例如：

```text
model/mjcf/mjcf_simready.xml
model/mjcf/mjcf_simready.xml~
```

## Check

按 `c` 后会进入 check 配置确认态。此时只接受 `m`、数字、Backspace、`?`、`y`、`n`，其他按键会被屏蔽，避免误触主界面操作。

```text
m                  切换 ignore metadata，默认 on
0-9                输入 stop depth
Backspace          删除 stop depth 的最后一位
?                  显示 check help
y                  执行 check
n                  取消 check
```

`ignore metadata: on` 时，same-size/different-mtime 文件会用 rsync checksum 判断内容；内容相同则视为 same，内容不同才视为 diff。`ignore metadata: off` 时，mtime 不同按旧式 metadata diff 处理。

`stop depth` 为空表示完整递归检查。输入非负整数后，depth 相对每个选中根计算；选中根为 depth 0。启用后会先加载到 `stop depth + 1` 层，再在每个 stop-depth 单元内继续向下检查；遇到 remote-only、同路径文件/目录类型冲突或内容不同会停止该单元剩余未检查分支，继续下一个同级单元。local-only 不触发短路，local-only/remote-only 目录在 check 中都不会继续深入；手动展开目录的浏览行为不变。

## 键盘操作

```text
Up / Down          移动光标
Left               折叠目录 / 回到父目录
Right / Enter      展开目录 / 进入第一个子节点
Space              切换选择
d                  下载选中项
u                  上传选中项
f                  内置弹窗预览当前文件 diff
F                  外部工具预览当前文件 diff（默认 vim -d）
p                  对选中远端项递归变更权限
c                  配置并递归检查选中项
x                  清空选择
r                  刷新 manifest
?                  显示帮助
q                  退出
```

## 鼠标操作

```text
滚轮上 / 下         移动光标
单击行             移动光标到该行
单击复选框列       切换该行选择
双击目录           展开或折叠目录
双击底部快捷键     触发 Space/d/u/f/p/P/c/x/r/? 对应功能
```

## 版本

版本变更记录见 `CHANGELOG.md`。

当前发布 tag：

```text
v0.2.8
v0.2.7
v0.2.6
v0.2.5
v0.2.4
v0.2.3
v0.2.2
v0.2.1
v0.2.0
v0.1.10
v0.1.9
v0.1.8
v0.1.7
v0.1.6
v0.1.5
v0.1.4
v0.1.3
v0.1.2
v0.1.1
v0.1.0
```
