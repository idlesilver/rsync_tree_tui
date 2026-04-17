# Changelog

所有重要变更都会记录在这里。

格式遵循 Keep a Changelog，版本号遵循 Semantic Versioning。

## [Unreleased]

- v0.1.2 计划加入鼠标操作，包括滚轮滚动、点击选择和双击展开/折叠。

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
