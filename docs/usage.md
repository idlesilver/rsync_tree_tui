# Usage Guide

本文记录 `rsync-tree-tui` 的完整操作说明。快速开始见 [README](../README.md)，权限模型细节见 [Permission Rules](permission-rules.md)。

## Keyboard

```text
Up / Down          移动光标
Left               折叠目录 / 回到父目录
Right / Enter      展开目录 / 进入第一个子节点
Space              切换选择
d                  下载选中项
u                  上传选中项
f                  内置弹窗预览当前文件 diff
F                  外部工具预览当前文件 diff
o                  用编辑器打开 local 文件
O                  打开 remote 临时副本，修改后可确认单文件上传
p                  对选中 remote 项递归变更权限
P                  切换 PERM 列：badge / owner / group / mode
c                  配置并递归检查选中项
x                  清空选择
r                  刷新 manifest
?                  显示帮助
q                  退出
```

## Mouse

```text
滚轮上 / 下         移动光标
单击行             移动光标到该行
单击复选框列       切换该行选择
双击目录           展开或折叠目录
双击底部快捷键     触发 Space/d/u/f/o/p/P/c/x/r/? 对应功能
```

## Sync

`u` upload：local -> remote。

`d` download：remote -> local。

目录选择会先展开成显式 file list，再交给 rsync `--files-from`。下载会使用 rsync `--backup --whole-file`：

- `--whole-file` 让远端覆盖本地时直接传完整文件，避免用本地旧文件作为 delta basis 时出现 verification failed。
- `--backup` 没有配置 `--backup-dir`，所以被覆盖的本地旧文件会保存在原文件同目录，默认文件名追加 `~` 后缀。

```text
model/mjcf/mjcf_simready.xml
model/mjcf/mjcf_simready.xml~
```

upload/download 失败时，前台会显示：

- rsync exit code
- 保留下来的完整 log 路径
- 最近的相关错误行，例如 `rsync:`、`failed`、`denied`、`No such file`、`vanished`、`warning`

这用于定位 `rsync exit code 23` 这类部分传输失败。成功的临时 rsync log 会自动删除。

## Diff Preview

`f` 使用内置弹窗预览当前文件 diff。弹窗支持：

```text
Esc                关闭
Up / Down          上下滚动
Left / Right       横向滚动长行
PageUp / PageDown  翻页
Home / End         回到行首 / 行尾
```

`F` 使用外部 diff viewer。配置见 [Configuration](configuration.md)。

## File Open

`o` 直接打开 local 文件。编辑器退出后刷新当前文件 manifest。

`O` 会先把 remote 文件拉到本地临时副本，用编辑器打开。临时副本有修改时，会提示是否执行单文件 upload；确认后复用现有 upload/rsync 逻辑写回 remote。

如果使用系统 GUI opener 这类 view-only opener，remote 临时副本只作为查看，不会提示上传修改。

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

## Permission

TUI 中按 `p` 可以直接对选中的 remote 文件或目录递归应用权限模式。权限执行只修改 owner 是当前 remote 用户的条目；非 owner 条目会跳过，并在前台日志中按 owner=count 汇总。

文件很多时，远端 `find` / `chgrp` / `chmod` 可能长时间没有输出。前台日志界面会定期打印 `... permission still running` 和 elapsed 时间，表示权限进程仍在运行。

权限模型分为 read、write、group 三个维度：

```text
read:   pvt / grp / any
write:  pvt / grp
group:  not change group / selected group / input group
```

如果没有配置 selected group，或需要临时覆盖，可以在 permission 弹窗中用 `g` 切到 input group，按 `G` 输入 group。输入后必须按 Enter 在 remote 侧通过 `getent group` 验证，验证通过后才允许继续执行。

常规 `write=grp` 不会赋予 other write；`[any:g]` 表示 any readable + group writable。只有隐藏高级快捷键 `W` 可以进入 `write=any`，并且执行时需要按两次 `y` 确认。

`--permission-group` / `RSYNC_TREE_TUI_PERMISSION_GROUP` 提供一个可选 selected group；弹窗中 group 不是 `not change group` 时就会执行 `chgrp`，与 read/write 选择独立。

TUI 在 LOCAL 和 REMOTE 中间使用独立 `PERM` 列显示 remote 权限。按 `P` 可在 badge、owner、group、mode 视图之间切换。owner/group 视图会按当前可见最长 owner/group 名称扩宽 PERM 列。

完整显示规则、颜色、文件/目录权限、owner/group/others 行为和修改语义见 [Permission Rules](permission-rules.md)。

## Permission Script

`setup_remote_permissions.sh` 提供与 TUI permission 相同的规则，可作为独立工具使用。脚本应该在目标端运行。先把脚本复制到远程机器，再对远程目录执行 dry-run，确认后再应用：

```bash
scp setup_remote_permissions.sh user@host:/tmp/setup_remote_permissions.sh

ssh user@host 'bash /tmp/setup_remote_permissions.sh --dry-run --group asset_team grp:grp /remote/storage/staging'
ssh user@host 'bash /tmp/setup_remote_permissions.sh --group asset_team --owner chenhaozhe grp:grp /remote/storage/staging'
```

常用模式：

```bash
# 目标端：发布后的数据集只允许浏览和下载
bash /tmp/setup_remote_permissions.sh any:pvt /remote/storage/datasets/v1.0

# 目标端：开放 staging 目录，允许团队上传
bash /tmp/setup_remote_permissions.sh --group asset_team any:grp /remote/storage/datasets/staging

# 目标端：隐藏工作中目录
bash /tmp/setup_remote_permissions.sh pvt:pvt /remote/storage/wip_secret
```

脚本默认不修改 group，且只处理运行用户 owner 的条目；可以通过环境变量 `GROUP` / `OWNER` 或 `--group` / `--owner` 覆盖。
