# Changelog

所有重要变更都会记录在这里。

格式遵循 Keep a Changelog，版本号遵循 Semantic Versioning。

## [Unreleased]

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
