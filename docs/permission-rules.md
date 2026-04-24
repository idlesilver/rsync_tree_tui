# Permission Rules

本文定义 `rsync-tree-tui` 中远端权限类别的显示和修改规则。

TUI 对远端文件和目录都显示权限标记。标准类别固定为三个字符：

```text
[pvt]  private
[rdo]  read-only
[pub]  public
```

如果远端条目的权限不符合这三类规则，TUI 直接显示数字权限，例如 `[640]`、`[750]`、`[666]`，不显示 `[custom]`。

TUI 在 LOCAL 和 REMOTE 中间使用独立 `PERM` 列显示权限标记，所有远端条目的 badge 都在该列对齐。颜色含义：

| Badge | 颜色 |
| --- | --- |
| `[pvt]` | 灰色 |
| `[rdo]` | 棕色 |
| `[pub]` | 绿色 |
| `[640]` 等数字权限 | 紫色 |

## 显示规则

文件和目录使用两套判定规则，因为目录的 `x` 表示进入/遍历，文件的 `x` 表示执行。标准类别按完整 POSIX mode 模板判定，避免 owner 位异常时仍显示成共享类别。

| 条目类型 | `[pvt]` | `[rdo]` | `[pub]` | 数字 fallback |
| --- | --- | --- | --- | --- |
| 目录 | `700` | `755` | `775` | 其他任何权限组合显示 `[mode]`，如 `[750]` |
| 文件 | `600` | `644` | `664` | 其他任何权限组合显示 `[mode]`，如 `[640]` |

说明：

- 目录 setgid 不影响类别判定：`2700` 显示 `[pvt]`，`2755` 显示 `[rdo]`，`2775` 显示 `[pub]`。
- 除目录 setgid 外，其他特殊位或 execute 位不符合三类模板时，显示数字权限。
- 数字 fallback 使用三位八进制权限，不包含 setuid/setgid/sticky 位。

## 类别总览

| 类别 | 文件夹权限 | 子级默认行为 | 文件权限 |
| --- | --- | --- | --- |
| `[pvt]` | `700`：owner 可读写进入，group/others 无权限 | 修改操作会递归把已有子级改为 `[pvt]`；未来新子级默认行为取决于远端 umask/ACL/rsync 策略 | `600`：owner 可读写，group/others 无权限 |
| `[rdo]` | `755`：owner 可维护，group/others 可读可进入；有共享 group 时可为 `2755` | 修改操作会递归把已有子级改为 `[rdo]`；有共享 group 时目录 setgid 只保证 group 继承，不保证新文件自动 `644` | `644`：owner 可读写，group/others 只读 |
| `[pub]` | `775`：owner/group 可维护，others 可读可进入；有共享 group 时可为 `2775` | 修改操作会递归把已有子级改为 `[pub]`；有共享 group 时目录 setgid 只保证 group 继承，新文件是否 group writable 仍受 umask/ACL/rsync 策略影响 | `664`：owner/group 可读写，others 只读 |

## 文件级别能力

TUI 中的“看/展开”指远端条目是否可见、目录是否可进入并列出子项。“下载”指读取远端内容。“上传”指向远端目录创建内容或覆盖已有远端文件。

| 类别 | 身份 | 看/展开 | 下载 | 上传/覆盖 |
| --- | --- | --- | --- | --- |
| `[pvt]` | owner | 可以 | 可以 | 可以 |
| `[pvt]` | group | 不可以 | 不可以 | 不可以 |
| `[pvt]` | others | 不可以 | 不可以 | 不可以 |
| `[rdo]` | owner | 可以 | 可以 | 可以 |
| `[rdo]` | group | 可以 | 可以 | 不可以 |
| `[rdo]` | others | 可以 | 可以 | 不可以 |
| `[pub]` | owner | 可以 | 可以 | 可以 |
| `[pub]` | group | 可以 | 可以 | 可以 |
| `[pub]` | others | 可以 | 可以 | 不可以 |

上传能力需要同时满足目标路径上的 POSIX 权限：

- 向目录中新建文件：目标目录通常需要 `w+x`。
- 覆盖已有文件：目标文件通常需要 `w`，并可能受目录权限、rsync 行为和服务端挂载策略影响。
- TUI 只能根据 manifest 中的 owner/group/mode 做静态判断；最终结果仍以远端文件系统执行结果为准。

## 子级默认行为

`pvt/rdo/pub` 修改操作会递归调整当前已有的目标和子级内容。

未来新建子级是否自动保持同类权限，取决于远端环境：

- 普通 POSIX chmod 不能单独保证未来新文件权限。
- `[pub]` 和有共享 group 的 `[rdo]` 目录可设置 setgid，使新子级继承目录 group。
- 新文件是否 group writable/readable 仍受 umask、rsync 参数、默认 ACL、服务端策略影响。
- 如果站点需要强约束未来默认权限，建议配合默认 ACL 或统一的 rsync chmod 策略。

## 修改规则

TUI 中按 `p` 或运行 `setup_remote_permissions.sh` 修改权限时，规则按“修改到目标类别”定义。操作前应检查选中远端路径及其递归内容都属于当前 SSH 用户；否则拒绝执行，避免半改他人文件。

### 修改到 `[pvt]`

目标：只有 owner 可访问；group 和 others 都不能看、不能下载、不能上传。

| 对象 | owner 改动 | group 改动 | others 改动 | group ownership |
| --- | --- | --- | --- | --- |
| 目录 | 设置为 `rwx` | 设置为 `---`，移除 setgid | 设置为 `---` | 有 `permission_group`：best-effort `chgrp -R <group>`；无：不 chgrp。访问结果不依赖 group |
| 文件 | 设置为 `rw-` | 设置为 `---` | 设置为 `---` | 有 `permission_group`：best-effort `chgrp -R <group>`；无：不 chgrp。访问结果不依赖 group |

等价 chmod 语义：

```text
directories: u=rwx,go-rwx,g-s
files:       u=rw,go-rwx
```

### 修改到 `[rdo]`

目标：owner 可维护；group 和 others 可看、可下载，但不可上传或覆盖。

| 对象 | owner 改动 | group 改动 | others 改动 | group ownership |
| --- | --- | --- | --- | --- |
| 目录 | 设置为 `rwx` | 设置为 `r-x`；有共享 group 时设置 setgid | 设置为 `r-x` | 有 `permission_group`：best-effort `chgrp -R <group>`；无：不 chgrp |
| 文件 | 设置为 `rw-` | 设置为 `r--` | 设置为 `r--` | 有 `permission_group`：best-effort `chgrp -R <group>`；无：不 chgrp |

等价 chmod 语义：

```text
directories: u=rwx,go=rx
files:       u=rw,go=r
```

有 `permission_group` 时，目录额外设置 setgid：

```text
directories: u=rwx,go=rx,g+s
```

### 修改到 `[pub]`

目标：owner 和 group 可维护；others 只能看和下载，不能上传或覆盖。

| 对象 | owner 改动 | group 改动 | others 改动 | group ownership |
| --- | --- | --- | --- | --- |
| 目录 | 设置为 `rwx` | 设置为 `rwx`；有共享 group 时设置 setgid | 设置为 `r-x` | 有 `permission_group`：best-effort `chgrp -R <group>`；无：不 chgrp |
| 文件 | 设置为 `rw-` | 设置为 `rw-` | 设置为 `r--` | 有 `permission_group`：best-effort `chgrp -R <group>`；无：不 chgrp |

等价 chmod 语义：

```text
directories: ug=rwx,o=rx
files:       ug=rw,o=r
```

有 `permission_group` 时，目录额外设置 setgid：

```text
directories: ug=rwx,o=rx,g+s
```

## 实现约束

- `pvt/rdo/pub` 是完整 POSIX mode 模板，目录和文件分别判定。
- TUI 的 badge 应对文件和目录都显示。
- 三类规则之外的权限直接显示三位八进制 mode，例如 `[640]`。
- `rdo` 替代旧的 `ro`，以保持所有标准 badge 都是三个字符。
