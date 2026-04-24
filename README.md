# rsync-tree-tui

`rsync-tree-tui` 是一个单文件 TUI 工具，用于对比本地目录和远端 rsync 目标，并交互式选择文件或目录进行上传、下载、校验和 diff preview。

当前版本：`v0.1.9`

## 运行

```bash
python rsync_tree_tui.py --local-root /path/to/local --remote user@host:/path/to/remote
python rsync_tree_tui.py --remote user@host:/path/to/remote
python rsync_tree_tui.py
python rsync_tree_tui.py --version
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

环境变量示例：

```bash
RSYNC_TREE_TUI_LOCAL_ROOT=/path/to/local
RSYNC_TREE_TUI_REMOTE=user@host:/path/to/remote
```

`.env` 默认从启动目录读取，也可以通过 `--env-file` 指定。

## 全局配置

首次运行会创建：

```text
~/.config/rsync-tree-tui/config.json
```

该文件维护 checksum 策略和成功连接过的 local/remote。没有传入 remote 时，工具会按访问次数列出历史连接，让用户输入 index 选择。TTY 环境中，remote 的 user、host、path 会用不同颜色提示；非 TTY 或设置 `NO_COLOR` 时输出纯文本。

配置样例见 `config.example.json`。

## 远程权限辅助脚本

`setup_remote_permissions.sh` 用于在远程机器上批量整理共享目录权限。它会影响 TUI 里远端目录旁边的权限标记：

```text
public    -> [pub]  group read/write，可上传
readonly  -> [ro]   group read only，可浏览和下载
private   -> [pvt]  group/others 无访问权限
```

这个脚本应该在远程端运行。先把脚本复制到远程机器，再对远程目录执行 dry-run，确认后再应用：

```bash
scp setup_remote_permissions.sh user@host:/tmp/setup_remote_permissions.sh

ssh user@host 'bash /tmp/setup_remote_permissions.sh --dry-run --group shared public /remote/storage/staging'
ssh user@host 'bash /tmp/setup_remote_permissions.sh --group shared public /remote/storage/staging'
```

常用模式：

```bash
# 远程端：发布后的数据集只允许浏览和下载
bash /tmp/setup_remote_permissions.sh readonly /remote/storage/datasets/v1.0

# 远程端：开放 staging 目录，允许团队上传
bash /tmp/setup_remote_permissions.sh public /remote/storage/datasets/staging

# 远程端：隐藏工作中目录
bash /tmp/setup_remote_permissions.sh private /remote/storage/wip_secret
```

脚本默认 group 是运行用户的 primary group，也可以通过环境变量或 `--group` 指定。需要持久化站点默认值时，直接编辑脚本开头的 `GROUP="${GROUP:-$(id -gn)}"`。

`private` 会让目标目录在父目录中仍可被看到，并显示为 `[pvt]`；目标目录和所有子项会移除 group/others 权限，因此其他人看不到内部文件。

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
- TUI 内 `c` 检查动作仍会对选中项执行 checksum 内容校验。

## 键盘操作

```text
Up / Down          移动光标
Left               折叠目录 / 回到父目录
Right / Enter      展开目录 / 进入第一个子节点
Space              切换选择
d                  下载选中项
u                  上传选中项
p                  预览当前文件 diff
c                  递归检查选中项
x                  清空选择
r                  刷新 manifest
?                  显示帮助
q / Esc            退出
```

## 鼠标操作

```text
滚轮上 / 下         移动光标
单击行             移动光标到该行
单击复选框列       切换该行选择
双击目录           展开或折叠目录
双击底部快捷键     触发 Space/d/u/p/c/x/r/? 对应功能
```

## 版本

版本变更记录见 `CHANGELOG.md`。

当前发布 tag：

```text
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
