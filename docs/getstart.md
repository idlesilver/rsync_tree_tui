# Get Started

这是一套完全在本机运行的交互练习，用来快速体验 `rsync-tree-tui` 的主要工作流。它不需要 SSH，不会读取或修改真实项目数据；所有操作都发生在 `/tmp/rsync-tree-tui-example-$USER/`。

先创建 example，再启动 TUI。各节验证命令都是可选的，可以完成 TUI 练习并退出后再执行。

教程中的代码块可以直接复制。正文只讲完成练习所需的信息；完整行为和配置细节请继续阅读各节末尾链接的文档。

## 进入仓库

先进入仓库根目录。请把路径替换为你的实际 clone 路径：

```bash
cd /path/to/rsync-tree-tui
```

确认必需命令可用：

```bash
# Check required commands
command -v python rsync diff find
```

如果系统只提供 `python3`，将下文的 `python` 替换为 `python3`。

## 一次性创建 example

完整复制下面的代码块。它会一次性创建本教程需要的全部场景；如果目标目录已经存在，它不会覆盖已有练习结果。

```bash
EXAMPLE_ROOT="${TMPDIR:-/tmp}/rsync-tree-tui-example-${USER:-user}"

if [ -e "$EXAMPLE_ROOT" ]; then
  printf 'Example already exists: %s\n' "$EXAMPLE_ROOT"
  printf 'Clean it first if you want to start over.\n'
else
  # Create feature directories on both sides
  mkdir -p "$EXAMPLE_ROOT"/{local,remote}/{01_compare,02_diff,03_upload,04_download,05_check,06_edit,07_permission,08_pagination}

  # 01_compare: same, local-only, and remote-only files
  printf 'same on both sides\n' > "$EXAMPLE_ROOT/local/01_compare/same.txt"
  cp -p "$EXAMPLE_ROOT/local/01_compare/same.txt" "$EXAMPLE_ROOT/remote/01_compare/same.txt"
  printf 'only on local\n' > "$EXAMPLE_ROOT/local/01_compare/local_only.txt"
  printf 'only on remote\n' > "$EXAMPLE_ROOT/remote/01_compare/remote_only.txt"

  # 02_diff: one path with different text on each side
  printf 'title: local version\nstatus: draft\n' > "$EXAMPLE_ROOT/local/02_diff/settings.txt"
  printf 'title: remote version\nstatus: published\n' > "$EXAMPLE_ROOT/remote/02_diff/settings.txt"

  # 03_upload: a local-only directory with nested files
  mkdir -p "$EXAMPLE_ROOT/local/03_upload/package/nested"
  printf 'upload root file\n' > "$EXAMPLE_ROOT/local/03_upload/package/README.txt"
  printf 'upload nested file\n' > "$EXAMPLE_ROOT/local/03_upload/package/nested/data.txt"

  # 04_download: a remote-only file and an overwrite with backup
  printf 'download me\n' > "$EXAMPLE_ROOT/remote/04_download/remote_only.txt"
  printf 'old local value\n' > "$EXAMPLE_ROOT/local/04_download/replace_me.txt"
  printf 'new remote value\n' > "$EXAMPLE_ROOT/remote/04_download/replace_me.txt"

  # 05_check: identical content with deliberately different mtimes
  printf 'content is identical\n' > "$EXAMPLE_ROOT/local/05_check/metadata_only.txt"
  cp -p "$EXAMPLE_ROOT/local/05_check/metadata_only.txt" "$EXAMPLE_ROOT/remote/05_check/metadata_only.txt"
  touch -d '2024-01-01 00:00:00 UTC' "$EXAMPLE_ROOT/local/05_check/metadata_only.txt"
  touch -d '2024-01-02 00:00:00 UTC' "$EXAMPLE_ROOT/remote/05_check/metadata_only.txt"

  # 06_edit: one editable file on each side
  printf 'edit this local file\n' > "$EXAMPLE_ROOT/local/06_edit/local_file.txt"
  printf 'edit this remote file\n' > "$EXAMPLE_ROOT/remote/06_edit/remote_file.txt"

  # 07_permission: a dedicated remote-only permission target
  mkdir -p "$EXAMPLE_ROOT/remote/07_permission/target"
  printf 'permission demo\n' > "$EXAMPLE_ROOT/remote/07_permission/target/data.txt"
  chmod 755 "$EXAMPLE_ROOT/remote/07_permission/target"
  chmod 644 "$EXAMPLE_ROOT/remote/07_permission/target/data.txt"

  # 08_pagination: 25 identical files on both sides
  for index in {01..25}; do
    printf 'pagination file %s\n' "$index" > "$EXAMPLE_ROOT/local/08_pagination/file_${index}.txt"
    cp -p "$EXAMPLE_ROOT/local/08_pagination/file_${index}.txt" "$EXAMPLE_ROOT/remote/08_pagination/file_${index}.txt"
  done

  printf 'Example created: %s\n' "$EXAMPLE_ROOT"
fi
```

可以先确认顶层结构：

```bash
EXAMPLE_ROOT="${TMPDIR:-/tmp}/rsync-tree-tui-example-${USER:-user}"
find "$EXAMPLE_ROOT" -maxdepth 2 -type d -printf '%P/\n' | sort
```

预期看到 `local/` 和 `remote/`，两侧下面都有 `01_compare/` 到 `08_pagination/`。

## 启动 TUI

运行：

```bash
EXAMPLE_ROOT="${TMPDIR:-/tmp}/rsync-tree-tui-example-${USER:-user}"

python rsync_tree_tui.py \
  --config "$EXAMPLE_ROOT/config.json" \
  --local-root "$EXAMPLE_ROOT/local" \
  --remote "$EXAMPLE_ROOT/remote"
```

这里把本地目录作为 remote 使用，因此不需要 SSH。独立的 `config.json` 也会把本次练习产生的连接历史隔离在 example 目录中，清理 example 时会一并删除。

界面左侧是 LOCAL，右侧是 REMOTE。先记住这些基础按键：

```text
Up / Down          移动光标
Right / Enter      展开目录
Left               折叠目录或回到父目录
Space              选择当前文件或目录
```

深入阅读：[Usage Guide](usage.md#keyboard)

## 比较目录树

> 认识 same、local-only 和 remote-only 三种基础状态。

移动到 `01_compare/`，按 `Right` 展开。观察：

- `same.txt` 两侧都存在。
- `local_only.txt` 只显示在 LOCAL。
- `remote_only.txt` 只显示在 REMOTE。

## 查看文本差异

> 使用内置 diff 查看同一路径的内容差异。

展开 `02_diff/`，将光标移动到 `settings.txt`，按 `f`。在弹窗中使用方向键滚动，按 `Esc` 关闭。

预期 TUI 弹窗显示 `local version` / `remote version`、`draft` / `published` 的差异。

深入阅读：[Usage Guide](usage.md#diff-preview)

## Upload 一个目录

> 把 local-only 目录及其嵌套文件递归上传到 remote。

展开 `03_upload/`，移动到 LOCAL 一侧的 `package/`：

- 按 `Space` 选择 `package/`。
- 按 `u` 准备 upload。
- 按 `y` 确认。
- rsync 完成后按 `Enter` 返回 TUI。

预期 remote 中出现 `README.txt` 和 `nested/data.txt`，TUI 同步完成后会自动刷新。

按 `x`、再按 `y`，清空本节留下的选择。

深入阅读：[Usage Guide](usage.md#sync)

## Download 与本地备份

> 下载 remote-only 文件，并观察覆盖已有 local 文件时生成的 `~` 备份。

展开 `04_download/`：

- 选择 REMOTE 一侧的 `remote_only.txt`，按 `d`、`y`，完成后按 `Enter`。
- 按 `x`、`y` 清空选择。
- 选择两侧都存在的 `replace_me.txt`，再次按 `d`、`y`，完成后按 `Enter`。

预期 LOCAL 中出现 `remote_only.txt`，`replace_me.txt` 更新为 remote 内容，并新增保存旧内容的 `replace_me.txt~`。

按 `x`、`y` 清空选择。

深入阅读：[Usage Guide](usage.md#sync)

## Check 内容而忽略 metadata

> 确认内容相同但 mtime 不同的文件实际一致。

展开 `05_check/`，选择 `metadata_only.txt`：

- 按 `c` 进入 check 确认状态。
- 保持默认的 `ignore metadata: on` 和空的 stop depth。
- 按 `y` 执行。

预期 check 完成后，TUI 把该文件标记为内容已确认相同；两侧 mtime 不会被修改。

按 `x`、`y` 清空选择。stop depth 是大目录检查优化，详见 [Usage Guide](usage.md#check)。

## 打开和编辑文件

> 使用 `o` 编辑 local 文件，使用 `O` 编辑 remote 临时副本并写回 remote。

本节需要 `vim`、`nvim` 或你在配置中指定的可修改编辑器；如果没有，可以跳过本节。

展开 `06_edit/`：

- 移动到 `local_file.txt`，按 `o`，修改内容、保存并退出编辑器。
- 移动到 `remote_file.txt`，按 `O`，修改临时副本、保存并退出。
- TUI 提示是否上传修改后的 remote 文件时按 `y`。
- 上传完成后按 `Enter` 返回 TUI。

预期两个文件都包含你在编辑器中保存的新内容。

深入阅读：[Configuration](configuration.md#file-editor-和-image-opener)

## 查看和修改权限

> 切换 PERM 列视图，并在专用 example 目录上实际应用 private 权限。

展开 `07_permission/`：

- 连续按大写 `P`，观察 PERM 列在 badge、owner、group、mode 之间切换。
- 移动到 REMOTE 一侧的 `target/`，按 `Space` 选择。
- 按小写 `p` 打开权限弹窗；保持默认 `read: pvt`、`write: pvt`、`not change group`。
- 按 `y` 继续，再按 `y` 确认执行。
- 权限命令完成后按 `Enter` 返回 TUI。

预期目录 mode 为 `700`，文件 mode 为 `600`；TUI badge 显示 private 类别。

按 `x`、`y` 清空选择。

深入阅读：[Permission Rules](permission-rules.md) 和 [Usage Guide](usage.md#permission)

## 浏览分页目录

> 了解目录超过默认 20 项时的分页显示。

展开 `08_pagination/`。界面先显示前 20 个文件和 `... 5 more`；移动到 `... 5 more`，按 `Right` 或 `Enter` 加载其余文件。

预期加载分页后可以浏览全部 25 个文件。

深入阅读：[Usage Guide](usage.md#keyboard)

## 刷新、帮助与退出

这些操作不会修改文件，可以直接尝试：

```text
r                  刷新 local / remote manifest
?                  打开帮助；按 Esc 关闭
x, then y          清空全部选择
q                  退出 TUI
```

如果文件在 TUI 外发生变化，按 `r` 可以重新加载状态。完成练习后按 `q` 退出。

涉及文件修改的练习，可以在退出 TUI 后集中检查结果：

```bash
EXAMPLE_ROOT="${TMPDIR:-/tmp}/rsync-tree-tui-example-${USER:-user}"

# Inspect uploaded, downloaded, edited, and permission-modified files
find "$EXAMPLE_ROOT/remote/03_upload/package" -type f -printf '%P\n' | sort
cat "$EXAMPLE_ROOT/local/04_download/remote_only.txt"
cat "$EXAMPLE_ROOT/local/04_download/replace_me.txt"
cat "$EXAMPLE_ROOT/local/04_download/replace_me.txt~"
cat "$EXAMPLE_ROOT/local/06_edit/local_file.txt"
cat "$EXAMPLE_ROOT/remote/06_edit/remote_file.txt"
stat -c '%a  %n' \
  "$EXAMPLE_ROOT/remote/07_permission/target" \
  "$EXAMPLE_ROOT/remote/07_permission/target/data.txt"
```

预期能看到上传后的两个文件、下载后的新旧内容、编辑结果，以及权限 mode `700` / `600`。

## 可选清理

退出 TUI 后复制下面的命令。它会先显示将要删除的目录，只有输入 `y` 才会清理。

```bash
EXAMPLE_ROOT="${TMPDIR:-/tmp}/rsync-tree-tui-example-${USER:-user}"

printf 'Remove example directory %s? [y/N] ' "$EXAMPLE_ROOT"
read -r answer
if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
  # Remove only this tutorial workspace
  rm -rf -- "$EXAMPLE_ROOT"
  printf 'Removed: %s\n' "$EXAMPLE_ROOT"
else
  printf 'Kept: %s\n' "$EXAMPLE_ROOT"
fi
```

## 下一步

你已经实际完成了目录比较、内置 diff、递归 upload、download 与备份、checksum check、文件编辑、权限修改和分页浏览。

以下功能依赖真实环境或额外工具，不放进隔离 example：

- SSH、GVFS、本地 remote 和多个项目 remote：[Configuration](configuration.md#path-解析)
- `.env`、历史连接和配置优先级：[Configuration](configuration.md#配置来源)
- 外部 diff viewer、编辑器和 image opener：[Configuration](configuration.md#diff-viewer)
- stop depth 与完整操作语义：[Usage Guide](usage.md#check)
- 权限模式和 group 行为：[Permission Rules](permission-rules.md)
- 自动更新：[Configuration](configuration.md#auto-update)
