# Permission Rules

本文定义 `rsync-tree-tui` 中远端权限的显示和修改规则。

权限修改模型有三个维度：

```text
read:   pvt / grp / any
write:  pvt / grp / any
group:  not change group / selected group
```

常规小写 `w` 只在 `pvt` / `grp` 写权限之间切换，不会赋予 other write。隐藏高级快捷键 `W` 只在 `read=any` 时生效，可以切换到 `write=any`，执行时需要按两次 `y` 确认。

## PERM 列

TUI 在 LOCAL 和 REMOTE 中间使用独立 `PERM` 列。按 `P` 在四种视图之间循环：

```text
badge -> owner -> group -> mode -> badge
```

badge 使用固定宽度，owner/group 按当前可见内容扩宽：

```text
[pvt--]
[grp-r]
[grp-w]
[pub-r]
[pub-w]
[2755 ]
[alice]
[asset]
[     ]
```

缺失元信息显示空白 `[     ]`。

颜色：

| 视图 | 颜色 |
| --- | --- |
| badge `[pvt--]` | 灰色 |
| badge `[grp-r]` / `[grp-w]` | `grp` 绿色；`r` 青色（与 remote-only 相同）；`w` 紫色 |
| badge `[pub-r]` / `[pub-w]` | `pub` 黄色；`r` 青色（与 remote-only 相同）；`w` 紫色 |
| public r/w 超过 group r/w | 整枚 badge 红色 |
| owner | 青色 |
| group | 绿色 |
| mode | 紫色 |
| unknown / blank | 白色 |

## Badge 判定

Badge 只摘要 group 和 other 的 read/write 位，不考虑 owner、execute、条目类型或 setuid/setgid/sticky 等特殊位。需要精确权限时按 `P` 切到 mode 视图。

正常权限按以下优先级显示：

```text
other 有 write  -> [pub-w]
other 有 read   -> [pub-r]
group 有 write  -> [grp-w]
group 有 read   -> [grp-r]
都没有          -> [pvt--]
```

因此 `755` 和 `775` 都显示 `[pub-r]`；两者的 group write 差异在 mode 视图中查看。write 优先于 read，所以 write-only 权限仍归入 `*-w`。

如果 other 拥有 group 没有的 read/write 位，则视为权限倒挂。此时 badge 改按 group 的 read/write 定级，并整枚显示红色；group 没有 read/write 时显示红色 `[pvt--]`。倒挂比较同样忽略 execute 位。

| Mode 示例 | Badge | 状态 |
| --- | --- | --- |
| `700` / `600` | `[pvt--]` | 正常 |
| `750` / `640` | `[grp-r]` | 正常 |
| `770` / `660` | `[grp-w]` | 正常 |
| `755` / `644` | `[pub-r]` | 正常 |
| `775` / `664` | `[pub-r]` | 正常 |
| `777` / `666` | `[pub-w]` | 正常 |
| `746` | `[grp-r]` | 红色倒挂 |
| `714` / `702` | `[pvt--]` | 红色倒挂 |

## 修改规则

TUI 中按 `p` 或运行 `setup_remote_permissions.sh` 修改权限时，只修改 owner 是当前 SSH 用户（脚本中为 `--owner` / `OWNER`）的远端条目。非 owner 条目不会被修改，会在前台日志中按 owner=count 汇总。

TUI permission 的 `recursive` 默认 enabled。按大写 `R` 切换为 disabled 后，owner 统计、`chgrp` 和 `chmod` 都只处理每个选中联通分量的 root；完整选中的目录以目录自身为 root，部分选中的目录则使用其中各完整选中分支的顶层路径。该选择只对当前操作有效。独立脚本始终递归。

目录默认设置 `g+s` 继承 group，`pvt` 明确移除 `g+s`。文件使用 symbolic chmod，避免无意义地新增执行权限。

| Mode | 目录 chmod | 文件 chmod |
| --- | --- | --- |
| `pvt:pvt` | `u+rwx,go-rwx,g-s` | `u+rw,go-rwx` |
| `grp:pvt` | `u+rwx,g+rx,g-w,o-rwx,g+s` | `u+rw,g+r,g-w,o-rwx` |
| `grp:grp` | `u+rwx,g+rwx,o-rwx,g+s` | `u+rw,g+rw,o-rwx` |
| `any:pvt` | `u+rwx,g+rx,g-w,o+rx,o-w,g+s` | `u+rw,g+r,g-w,o+r,o-w` |
| `any:grp` | `u+rwx,g+rwx,o+rx,o-w,g+s` | `u+rw,g+rw,o+r,o-w` |
| `any:any` | `u+rwx,go+rwx,g+s` | `u+rw,go+rw` |

`selected group` 与 read/write 独立。只要弹窗中 group 不是 `not change group`，就会对 owner 匹配的条目执行：

```text
find -L <path> -user <owner> ! -group <group> -exec chgrp <group> {} +
```

如果 group 已经正确，不重复 chgrp。执行使用 bulk `find -exec ... {} +`，会遍历所有可进入目录，对 owner 匹配的文件和目录执行操作。统计阶段会显示 visible non-owned 条目的 owner；如果遇到不可进入的 non-owned 私有目录，只能统计到该目录本身的 owner，无法看到其子树。

执行阶段的 `find` / `chgrp` / `chmod` 失败会使本次 permission 显示为 completed with warnings；Ctrl+C 显示 interrupted。成功后 TUI 自动 refresh；warning 或中断后应按 `r` 刷新，查看远端真实状态。

## 弹窗交互

按 `p` 后弹窗维护四个状态：

```text
[r] read:   pvt / grp / any
[w] write:  pvt / grp
[g] group:  <selected group> / not change group
[R] recursive: enabled / disabled (roots only)
```

`recursive` 每次打开弹窗时默认为 enabled，按大写 `R` 只切换当前操作的递归范围。`read=pvt, write=grp` 不允许出现；如果切换 read 导致 write 超过 read，会自动降级。`write=any` 只通过隐藏高级快捷键 `W` 进入，`any` 会显示为红色，按 `y` 后必须再按一次 `y` 才执行。只有 `y` 进入确认，`Esc` 取消。

## 脚本

`setup_remote_permissions.sh` 接受新模式：

```text
pvt:pvt
grp:pvt
grp:grp
any:pvt
any:grp
any:any
```

为兼容旧调用，也接受并映射：

```text
pvt   -> pvt:pvt
grp:r -> grp:pvt
grp:w -> grp:grp
any:r -> any:pvt
any:w -> any:any
```

旧 `rdo` / `pub` 不兼容，直接报错。

脚本默认 `OWNER="$(id -un)"`，也可以传入：

```text
--owner USER
OWNER=USER
```
