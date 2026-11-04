# Google DESIGN.md 指南

Arka 内置了 Google 开放 **DESIGN.md** 格式的精选摘要，使 agent
在构建 UI 时能够应用一致的视觉识别——并配合
[前端内容指南](./frontend-content-guide.md) 处理面向用户的文案。

**上游规范：** https://github.com/google-labs-code/design.md

---

## 功能说明

- 针对前端/UI 目标、coding-tui 计划和 `frontend_loop` 审查自动注入
- 如果存在项目根目录下的 `DESIGN.md`，则优先使用
- 否则回退到内置的 `google-design.md`（格式规则 + agent 工作流）
- 提供 MCP / CLI 别名：`google-design`、`design.md`、`DESIGN.md`

---

## 环境

在 `~/.config/arka/.env` 中：

```bash
GOOGLE_DESIGN_GUIDE=1                 # default on
GOOGLE_DESIGN_GUIDE_MODE=auto         # auto | always | off
FRONTEND_CONTENT_GUIDE=1              # copy policy (paired by default)
```

将任一指南设置为 `0` 即可单独禁用。

---

## CLI

```bash
arka md_doc read google-design
arka md_doc read design.md            # project DESIGN.md if present
arka md_doc context google-design
```

自然语言（符号路由）：

```text
follow google design.md
use design.md for this UI
```

---

## MCP

`arka_markdown` 接受：

| 别名 | 解析为 |
|-------|-------------|
| `google-design` | 项目 `DESIGN.md` 或内置指南 |
| `design.md` | 同上 |
| `frontend-content-guide` | 内置文案政策 |

示例：`arka_markdown`，使用 `action=read`、`path=google-design`。

---

## 项目 DESIGN.md

在仓库根目录提交项目专属的 `DESIGN.md`（YAML token + markdown
章节）。Arka 会优先使用它，而不是内置摘要。使用以下命令验证：

```bash
npx @google/design.md lint DESIGN.md
```

完整的 token schema、章节顺序和 CLI 参考，请参阅
[官方规范](https://github.com/google-labs-code/design.md)。
