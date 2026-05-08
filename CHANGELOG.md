# Changelog

所有重要变更都会记录在这里。

格式遵循 Keep a Changelog，版本号遵循 Semantic Versioning。

## [Unreleased]

## [0.2.2] - 2026-05-08

### Added

- `c` check 进入配置确认态，支持 `m` 临时切换 ignore metadata、输入 stop depth、Backspace 修改 depth，并提供 check 专用 `?` help。
- stop-depth check：按每个选中根计算相对层级，先加载到 `depth + 1`，再在发现 remote-only、类型冲突或内容不同后短路当前层级单元并继续下一个单元。

### Changed

- check 默认启用 ignore metadata：same-size/different-mtime 文件会用 checksum 消除 metadata-only 误报；关闭后保留旧式 mtime diff 判断。
- check 不再深入 local-only 或 remote-only 目录；local-only 不触发 stop-depth 短路，remote-only 会触发短路。
- download rsync 命令增加 `--whole-file`，远端覆盖本地时不再依赖本地旧文件作为 delta basis。

### Fixed

- 修复 check 内容校验未将 same-content/different-mtime 文件标为相同的问题；这类文件此前可能仍保持红色，直到手动 diff 后才变绿。

## [0.2.1] - 2026-04-27

### Added

- 增加轻量 `VERSION` 文件用于远端版本探测。
- 默认启动时后台短超时检查 GitHub 最新版本并记录到配置；下次启动发现记录版本较新时，可选择立即更新、稍后提醒、跳过当前版本或关闭自动检查。

### Changed

- `.env` 中 `RSYNC_TREE_TUI_LOCAL_ROOT` 的相对路径现在相对 `.env` 所在目录解析，CLI 参数和 shell 环境变量保持相对启动目录解析。
- `--update` 和自动更新提示共用远端源码下载、版本解析和安装逻辑，并使用 SemVer 数字段比较版本；版本探测失败视为无更新，payload 下载或校验失败不会替换本地文件。

## [0.2.0] - 2026-04-24

### Added

- TUI 新增 `p` 远端权限操作，可对选中远端文件/目录递归应用 `pvt`、`rdo`、`pub`，执行前检查 owner 并要求 `y/n` 二次确认。
- 新增 `--permission-group` 和 `RSYNC_TREE_TUI_PERMISSION_GROUP`，并支持全局配置与 known connection 记录。

### Changed

- download 同步命令增加 rsync `--backup`，覆盖本地文件时保留 rsync 备份文件。
- 底部快捷键提示将 diff 改为 `f/F Diff`，`p` 改为远端权限操作入口。
- `f` 使用内置 diff 弹窗，`F` 使用外部 diff 工具；外部工具默认使用 `vim -d`，配置支持 `vimdiff`、`vim -d`、`nvim -d`，并兼容 `delta`。
- 内置 diff 弹窗支持左右横向移动长行，并避免长行或 ANSI 控制序列残片覆盖弹窗边框。
- 远端权限标记改为文件和目录都显示，标准类别为 `[pvt]`、`[rdo]`、`[pub]`；非标准权限显示为 `[640]` 等数字 mode，并在 LOCAL/REMOTE 中间独立 `PERM` 列对齐显示。
- 权限操作在执行远端归属检查前先更新 statusline，避免多选时界面看起来无响应。
- `setup_remote_permissions.sh` 同步精确权限模板：`pvt=700/600`、`rdo=755/644`、`pub=775/664`。

## [0.1.9] - 2026-04-24

### Changed

- 底部快捷键提示改为按键黄色、说明白色，并支持双击常用快捷键触发对应功能。

### Fixed

- 修复清空选择后 tree 仍可能显示旧选中状态的问题。

## [0.1.8] - 2026-04-22

### Added

- 目录分页显示：当目录子项超过 20 时，只显示前 20 个，剩余显示 `... N more`，按 Right/Enter 或点击可展开更多。
- `pagination_size` 配置项：可在 `config.json` 中设置每页显示数量，默认 20。
- Ctrl+C 中断：按 Ctrl+C 中断当前操作（加载/check/sync），但保持 TUI 运行。

### Changed

- 展开目录时加载一层完整 metadata，再按页显示，确保跨两侧排序和权限标记准确。
- 目录子项排序改为两侧都存在的条目优先，剩余 local-only/remote-only 按最后修改时间倒序显示。
- 缓存目录排序、选择状态和差异状态，避免在已加载大目录中移动光标时重复扫描全部子项。
- check 操作时全量加载，不限制分页。
- 修复 `... more` placeholder 渲染、计数、加载问题。

### Fixed

- `... more` placeholder 点击后真正加载下一页内容。
- 单侧大目录的子目录不再被误识别为文件。
- 分页加载后的远程目录保留真实权限标记和可展开状态。
- 本地已下载但不在远端前 20 个名字中的目录不再被误判为 local-only。
- 远程计数不再错误减 2。

## [0.1.7] - 2026-04-21

### Added

- `setup_remote_permissions.sh` 增加 `--version` 和 `--update` 参数，支持版本显示和从 GitHub 自更新。

### Changed

- LOCAL/REMOTE 标题下划线延伸到整个面板宽度。

## [0.1.6] - 2026-04-21

### Added

- `--update` 参数：从 GitHub 下载最新版本并替换本地文件，支持版本比较和自更新。

## [0.1.5] - 2026-04-17

### Changed

- `setup_remote_permissions.sh` 的默认 group 改为运行用户的 primary group，并支持 `GROUP=...` 或 `--group ...` 覆盖。
- `private` 模式现在会移除目标目录和所有子项的 group/others 权限，避免从 `readonly` 切换后 others 仍可读取内部内容。
- README 更新远程权限脚本的通用 group 和 private 语义说明。

## [0.1.4] - 2026-04-17

### Added

- 复制 `setup_remote_permissions.sh` 作为远程端权限辅助脚本，配合 TUI 中的 `[pub]`、`[ro]`、`[pvt]` 目录标记使用。
- README 增加远程端运行权限脚本的说明。

### Changed

- 主 TUI 在结构树和底部提示行之间增加分隔线。

## [0.1.3] - 2026-04-17

### Added

- README 增加 localhost 快速上手脚本，用两个相似但不同的临时目录演示对比流程。

### Changed

- 鼠标事件订阅收窄为点击、双击和滚轮，不再请求 mouse motion/report position，减少鼠标移动导致的重绘压力。
- 双击识别窗口从 300ms 缩短为 180ms，降低单击/双击反馈延迟。

## [0.1.2] - 2026-04-17

### Added

- 支持主列表鼠标操作：滚轮移动光标、单击行移动光标、单击复选框列切换选择、双击目录展开或折叠。
- 没有 local/remote 参数并进入 known connection picker 时，TTY 输出会用颜色区分 remote 的 user、host 和 path。

### Changed

- 帮助弹窗和 README 增加鼠标操作说明。

## [0.1.1] - 2026-04-17

### Changed

- 正常缺失侧不再显示 `<missing>` 文本，减少左右对比时的视觉干扰。
- listing error 仍显示 `<error>`，继续区分缺失文件和加载失败。

## [0.1.0] - 2026-04-17

### Added

- 从项目脚本抽取为通用单文件工具 `rsync-tree-tui`。
- 支持本地/远端目录树对比、懒加载浏览、选择子树、上传、下载、刷新和 diff preview。
- 支持配置优先级：CLI args > terminal env > `.env` > 当前工作目录或 known connection picker。
- 支持全局配置 `~/.config/rsync-tree-tui/config.json`，自动记录成功连接过的 local/remote。
- 支持 balanced checksum 策略，可按文件大小阈值和后缀决定 rsync 是否使用 checksum。
- 支持 `--version` 输出当前版本。

### Changed

- Manifest 解析使用 NUL 字段，避免路径中包含 tab 时解析失败。
- SSH ControlPath 使用临时目录短 hash，降低 socket path 过长风险。
- listing 失败显示为 error 状态，不再当作空目录处理。
