# rsync-tree-tui

`rsync-tree-tui` 是一个单文件 TUI 工具，用于对比 local 和 remote 两棵目录树，交互式选择文件或目录执行 upload、download、diff preview、checksum check 和权限调整。

当前版本：`v0.2.13`

## 快速开始

```bash
python rsync_tree_tui.py --local-root /path/to/local --remote user@host:/path/to/remote
python rsync_tree_tui.py --local-root /path/to/local --remote /path/to/other/local
python rsync_tree_tui.py
```

第一次使用建议阅读 [Get Started](docs/getstart.md)：它会在 `/tmp` 中创建完全隔离的 local/remote example，带你实际完成目录比较、diff、upload、download、check、文件编辑、权限修改和分页浏览，不需要 SSH。

推荐设置 alias：

```bash
alias rsynctui="python /path/to/rsync_tree_tui.py"
```

依赖命令：

```text
rsync
diff
GNU find with -printf
ssh（仅 SSH remote 模式需要）
getent（仅 permission input group 验证需要）
```

可选工具：

```bash
sudo apt install vim neovim timg
```

## Remote 写法

`remote` 可以是 SSH rsync 目标，也可以是本地路径：

```bash
rsynctui --remote user@host:/data/project
rsynctui --remote ssh-config-name:/data/project
rsynctui --remote /mnt/nas/project
rsynctui --remote '/run/user/1000/gvfs/smb-share:server=disk.galbot.vip,share=simvla/games'
```

以 `/`、`./`、`../`、`~` 开头或不含冒号的 `remote` 会按本地路径解析；`host:path` 这类歧义形式保持 SSH remote 语义。`local_root` 本身就是本地路径，也支持上面的 GVFS SMB 挂载路径。

## 常用按键

```text
Up / Down          移动光标
Left / Right       折叠 / 展开目录
Space              切换选择
d / u              download / upload 选中项
f / F              内置 / 外部 diff preview
o / O              打开 local / remote 文件
c                  配置并递归 check 选中项
p / P              修改权限 / 切换 PERM 列视图
x                  清空选择
r                  刷新 manifest
?                  显示帮助
q                  退出
```

upload/download 失败时会保留一份 rsync log，并在前台显示相关错误摘要，便于定位 `code 23` 这类部分失败。

## 配置入口

常用环境变量：

```bash
RSYNC_TREE_TUI_LOCAL_ROOT=/path/to/local
RSYNC_TREE_TUI_REMOTE=user@host:/path/to/remote
RSYNC_TREE_TUI_PERMISSION_GROUP=asset_team
```

配置来源优先级：

```text
local_root       --local-root > RSYNC_TREE_TUI_LOCAL_ROOT > .env > 当前工作目录
remote           --remote > RSYNC_TREE_TUI_REMOTE > .env single > .env indexed picker > known connection picker
permission_group --permission-group > RSYNC_TREE_TUI_PERMISSION_GROUP > .env > selected known connection > global config > 空
```

首次运行会创建全局配置：

```text
~/.config/rsync-tree-tui/config.json
```

详细配置见 [Configuration](docs/configuration.md)。

项目 `.env` 可以配置多个常用 remote：

```bash
RSYNC_TREE_TUI_REMOTE_0=/mnt/dev-nas/project
RSYNC_TREE_TUI_REMOTE_1=ssh-box:/data/project
```

未传 `--remote` 且没有单值 `RSYNC_TREE_TUI_REMOTE` 时，会用 index 选择项目 remote。

## 更多文档

- [Get Started](docs/getstart.md)：完全本地、可复制执行的主要功能上手教程。
- [Configuration](docs/configuration.md)：配置优先级、JSON 配置、编辑器、checksum、mouse wheel、auto update。
- [Usage Guide](docs/usage.md)：完整按键、同步行为、check、permission、rsync 失败日志。
- [Permission Rules](docs/permission-rules.md)：权限 badge、read/write/group 模型和脚本规则。
- [Changelog](CHANGELOG.md)：版本变更记录。
