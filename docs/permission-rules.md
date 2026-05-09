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

所有视图都保持固定括号位置 `[_____]`：

```text
[pvt:-]
[grp:r]
[grp:w]
[any:r]
[any:g]
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
| badge `[any:r]` / `[any:g]` / `[any:w]` | scope 蓝色；`r` 黄色；`g` 绿色；`w` 红色 |
| owner | 青色 |
| group | 绿色 |
| mode / numeric fallback | 紫色 |
| unknown / blank | 白色 |

## Badge 判定

Badge 只按新模型精确匹配；不再输出旧 `[rdo]` / `[pub]`。

| 条目类型 | `[pvt:-]` | `[grp:r]` | `[grp:w]` | `[any:r]` | `[any:g]` | `[any:w]` |
| --- | --- | --- | --- | --- | --- | --- |
| 目录 | `700` / `2700` | `750` / `2750` | `770` / `2770` | `755` / `2755` | `775` / `2775` | `777` / `2777` |
| 文件 | `600` | `640` | `660` | `644` | `664` | `666` |

其他权限显示数字 mode。目录 setgid 只在上述目录模板中被接受；其他特殊位显示数字。

## 修改规则

TUI 中按 `p` 或运行 `setup_remote_permissions.sh` 修改权限时，只修改 owner 是当前 SSH 用户（脚本中为 `--owner` / `OWNER`）的远端条目。非 owner 条目不会被修改，会在前台日志中按 owner=count 汇总。

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

按 `p` 后弹窗维护三个状态：

```text
[r] read:   pvt / grp / any
[w] write:  pvt / grp
[g] group:  <selected group> / not change group
```

`read=pvt, write=grp` 不允许出现；如果切换 read 导致 write 超过 read，会自动降级。`write=any` 只通过隐藏高级快捷键 `W` 进入，`any` 会显示为红色，按 `y` 后必须再按一次 `y` 才执行。只有 `y` 进入确认，`Esc` 取消。

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
