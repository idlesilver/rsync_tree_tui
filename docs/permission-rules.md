# Permission Rules

本文定义 `rsync-tree-tui` 中远端权限的显示和修改规则。

权限模型有两个维度：

```text
scope: pvt / grp / any
write: readonly / writable
```

`pvt` 不使用 write 维度，固定显示为 `[pvt:-]`。

## PERM 列

TUI 在 LOCAL 和 REMOTE 中间使用独立 `PERM` 列。按 `P` 在四种视图之间循环：

```text
badge -> owner -> group -> mode -> badge
```

所有视图都保持固定括号位置 `[_____]`：

```text
[pvt:-]
[grp:r]
[grp:w]
[any:r]
[any:w]
[ 755 ]
[2755 ]
[alice]
[asset]
[     ]
```

owner/group 超过 5 个字符时截断；缺失元信息显示空白 `[     ]`。

颜色：

| 视图 | 颜色 |
| --- | --- |
| badge `[pvt:-]` | 灰色 |
| badge `[grp:r]` / `[grp:w]` | scope 绿色；`r` 黄色；`w` 红色 |
| badge `[any:r]` / `[any:w]` | scope 蓝色；`r` 黄色；`w` 红色 |
| owner | 青色 |
| group | 绿色 |
| mode / numeric fallback | 紫色 |
| unknown / blank | 白色 |

## Badge 判定

Badge 只按新模型精确匹配；不再输出旧 `[rdo]` / `[pub]`。

| 条目类型 | `[pvt:-]` | `[grp:r]` | `[grp:w]` | `[any:r]` | `[any:w]` |
| --- | --- | --- | --- | --- | --- |
| 目录 | `700` / `2700` | `750` / `2750` | `770` / `2770` | `755` / `2755` | `777` / `2777` |
| 文件 | `600` | `640` | `660` | `644` | `666` |

其他权限显示数字 mode。目录 setgid 只在上述目录模板中被接受；其他特殊位显示数字。

## 修改规则

TUI 中按 `p` 或运行 `setup_remote_permissions.sh` 修改权限时，先做 permission preflight：当前实现要求选中远端路径及其递归内容都属于当前 SSH 用户，否则拒绝执行。

目录默认设置 `g+s` 继承 group，`pvt` 明确移除 `g+s`。文件使用 symbolic chmod，避免无意义地新增执行权限。

| Mode | 目录 chmod | 文件 chmod |
| --- | --- | --- |
| `pvt` | `u+rwx,go-rwx,g-s` | `u+rw,go-rwx` |
| `grp:r` | `u+rwx,g+rx,g-w,o-rwx,g+s` | `u+rw,g+r,g-w,o-rwx` |
| `grp:w` | `u+rwx,g+rwx,o-rwx,g+s` | `u+rw,g+rw,o-rwx` |
| `any:r` | `u+rwx,go+rx,go-w,g+s` | `u+rw,go+r,go-w` |
| `any:w` | `u+rwx,go+rwx,g+s` | `u+rw,go+rw` |

`selected group` 只对 `grp:*` 生效：

```text
find -L <path> ! -group <group> -exec chgrp <group> {} +
```

如果 group 已经正确，不重复 chgrp。任何 `chgrp` 或 `chmod` 失败都会使本次 permission 操作失败；中断或失败后应按 `r` 刷新，查看远端真实状态。

## 弹窗交互

按 `p` 后弹窗维护三个状态：

```text
[s] scope:  pvt / grp / any
[w] write:  readonly / writable
[g] group:  <selected group> / not change group
```

`scope != grp` 时 group 行变灰且不参与执行；`scope=pvt` 时 write 行变灰且结果固定为 `[pvt:-]`。只有 `y` 进入确认，`Esc` 取消。

## 脚本

`setup_remote_permissions.sh` 只接受新模式：

```text
pvt
grp:r
grp:w
any:r
any:w
```

旧 `rdo` / `pub` 不兼容，直接报错。
