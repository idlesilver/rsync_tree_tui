# rsync-tree-tui

`rsync-tree-tui` 是一个单文件 TUI 工具，用于对比本地目录和远端 rsync 目标，并交互式选择文件或目录进行上传、下载、校验和 diff preview。

当前版本：`v0.1.2`

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
```

## 版本

版本变更记录见 `CHANGELOG.md`。

当前发布 tag：

```text
v0.1.0
v0.1.1
v0.1.2
```
