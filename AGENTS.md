# 开发流程

## CHANGELOG
`CHANGELOG.md` 规则：

- 仅记录重要变更。
- 遵循 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)。
- 遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)。
- 合并重复或相关的 `Unreleased` 条目，而非按提交顺序逐条列出。
- 优先使用分组段落如 `Added`、`Changed`、`Fixed`、`Refactored`。


## RELEASE
`rsync-tree-tui` 发布规则：

- 保持此目录为独立 git 仓库，不通过父仓库管理。
- 常规任务只需更新代码、测试、README 和 CHANGELOG，除非用户明确要求 release，否则不要打 tag 或推送。
- 任务完成后告知用户可以触发 release。
- 用户明确触发 release 时，一次性完成完整发布流程：bump `__version__` 和 `VERSION` 文件、更新 `CHANGELOG.md` 和 `README.md`、创建 annotated `vX.Y.Z` tag、推送到 `origin` 和 `galbot`。
- 远程配置仅存在于本地 `.git/config`，不得写入已追踪文件。
- 忽略无关的未追踪文件，除非用户要求包含。

提交规则：

- 不添加 Co-Authored-By 信息。
