# 仓库结构

Arka 将运行时代码放在 `src/arka/` 下，可执行的维护辅助脚本放在
`scripts/` 中，测试放在 `tests/` 中，面向用户的文档放在 `docs/` 中。

## 源码树（已提交）

| 路径 | 用途 |
|------|---------|
| `src/arka/` | Python 包——技能、路由、集成 |
| `src/arka/agent/` | 面向用户的任务工作流 |
| `src/arka/core/` | 共享配置、安全、路由基础组件 |
| `src/arka/integrations/` | 外部系统和 MCP 适配器 |
| `src/arka/llm/` | 提供商、回退、模型选择 |
| `src/arka/routing/` | 符号路由和自然语言路由转换 |
| `src/arka/fish/`, `src/arka/bundled/` | Fish 运行时和同步的分发资源 |
| `bin/` | 旧版 CLI shim（安装时同步到 `bundled/`） |
| `scripts/` | 维护者工具（`sync_bundled.py`、发布、重新获取） |
| `tests/` | Pytest 测试套件 |
| `docs/` | Mintlify 文档 |
| `recordings/` | 精选演示录制（CLI 截图、终端记录） |
| `examples/` | 示例配置和测试工具 |

新的运行时功能应放在 `src/arka/` 下最窄的现有边界中，
并在面向用户时通过 `dispatch.py` 加上符号路由对外暴露。

## 本地状态（切勿提交）

可编辑的检出副本将可写的运行时状态存储在 **`<repo>/.arka/`** 中
（`config_dir()`）。已安装的副本使用 `~/.config/arka/`（如果
`~/.config/fish/` 目录中已存在 `.env`，则使用该旧版路径）。

| 位置 | 示例 |
|----------|----------|
| `<repo>/.arka/` 或 `~/.config/arka/` | `.env`, `mcp.json`, `personalize.json`, `email_contacts.json`, `email_draft_history.json`, `logs/mcp.jsonl`, `message-sessions/`, `personas/` |
| `~/.cache/arka/` | 临时缓存（支持通过 `CACHE_DIR` 覆盖） |
| `~/arka-generated/` | 来自 `view_data` / `generate_data` 的表格/数据导出（支持通过 `DATA_OUTPUT_DIR` 覆盖） |
| `<repo>/.arka-index` | 供 `repo_context` 使用的本地仓库索引（可重新生成） |

`arka doctor` 和 `ensure_layout()` 会调用 `migrate_scattered_state()`，将
历史遗留在仓库根目录的产物（`mcp.json`、`platform.json`、`logs/`、邮件
历史等）移动到 `.arka/` 中。迁移完成后，如果规范副本已位于 `.arka/` 下，
**仓库根目录中过时的重复文件可以安全删除**。

密钥只应放在配置 `.env` 中——切勿提交 `.env`、`your-secret-here`
占位符或工具凭据缓存（例如 `.local/state/gh/`）。

## 可重新生成的演示产物

`recordings/_demo_build/` 以及 `recordings/live-demo-ui/` 下按次运行生成的文件夹
是 ffmpeg/终端录制的**构建输出**。它们已被 gitignore；更新演示媒体时，
请使用 `recordings/` 中的脚本重新生成。

## 不应放在仓库根目录的内容

避免将以下内容放在检出根目录——它们应放在 `.arka/`、
`~/arka-generated/` 或 `/tmp` 下：

- `email_draft_history.json`、`email_contacts.json`
- `logs/mcp.jsonl`
- 本地 QA 产生的临时 `*-bug.md` 工单
- 名为 `agent/`、`llm/`、`stock/` 或 `personas/` 的空旧版文件夹（相关模块
  位于 `src/arka/` 下）
