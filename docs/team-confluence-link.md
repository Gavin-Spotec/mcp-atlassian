# 团队版 Jira–Confluence 关联工具

本仓库是 `sooperset/mcp-atlassian` 的团队 fork。新增工具是
`jira_ensure_confluence_link`（遵循上游 `jira_` 前缀），不是官方 Rovo MCP 工具，
也不使用 `ensure_jira_confluence_link` 这个未注册名称。

## 工具行为

```json
{
  "issue_key": "PROJ-123",
  "confluence_page_url": "https://your-site.atlassian.net/wiki/spaces/TEAM/pages/123456/Plan"
}
```

1. 使用当前请求的 Confluence 客户端读取页面，验证页面可访问、已发布，取得真实标题。
2. 按站点和页面 ID 查找关联。唯一普通 Web Link 原地修复，
   保留链接 ID、摘要、图标和状态；没有则创建，正确的关联直接复用。
3. 写入 `application.type=com.atlassian.confluence`、应用名称、
   `relationship=Wiki Page` 和页面信息。**无需查询或配置 `appId`。**
4. 新建链接使用规范页面 URL 的 SHA-256 构造稳定的 `globalId`，用于 Jira upsert；
   这是调用方自定义的标识。已有链接保留原来的 `globalId`，没有则仍不传，
   不改写既有的 `appId=...&pageId=...` 格式。
5. 再次读取关联并核对字段，只有验证成功才返回 `verified=true`。

`action` 为 `created`、`updated`、`unchanged` 或 `reconciled`。
`reconciled` 表示写请求超时或出现连接/服务端错误，但读回确认关联已正确存在；
无法确认则返回错误，不盲目重复写入。底层重试配置仍由上游控制，团队默认保持
`ATLASSIAN_RETRY_INCLUDE_WRITES=false`。

多个候选或身份冲突会报错，不自动删除关联。读回验证不等于验证 Jira UI 的
Attachments 展示；首次部署仍应在测试工单上人工检查页面卡片。
本工具不上传附件文件，也不修改 Confluence 正文或 Jira 描述。

## 适用范围与认证

- 第一版支持 Jira Cloud + Confluence Cloud，`CONFLUENCE_URL` 必须包含 `/wiki`。
- 页面 URL 支持 `/wiki/spaces/SPACE/pages/ID/...` 和
  `/wiki/pages/viewpage.action?pageId=ID`；短链接需要先换成完整页面地址。
- 复用上游认证、当前请求客户端、只读模式及 `jira_links` 工具集。
- Jira 凭据必须能查看目标工单并创建/更新 remote link；
  Confluence 凭据必须可以读取页面。无需管理员应用链接查询权限或额外站点映射。
- 复用上游的 API Token/OAuth 认证路径。真实联调使用普通成员的 Cloud API Token；
  OAuth 环境需要相应 Jira 写入和 Confluence 读取 scopes，本次未进行 OAuth 真机联调。
- 每位研发使用自己的凭据文件；不要把 token 放入仓库或团队共享配置。
  集中 HTTP 部署仍需按上游文档配置逐用户认证，本次没有新增认证代理。

## 已验证行为

2026-11-06 使用普通成员的现有 Cloud API Token，将已有普通 Web Link 原地补齐
Confluence 应用类型和关系字段，**请求未携带 `appId` 或 `globalId`**。
REST 读回确认链接 ID 保持不变；刷新 Jira 后，页面从 Web links 移到 Attachments。
这验证了该站点上修复路径的实际展示，不代表每个部署或界面版本都已验证。

工具只返回 REST 读回验证结果，不把 UI 展示写成自动检查通过。
早期开发版本要求的 `JIRA_CONFLUENCE_APP_LINK` 配置已移除，继续使用原有凭据即可。

## 本地使用

安装 uv 后，在仓库执行：

```bash
uv sync --frozen --all-extras --dev
uv run --frozen mcp-atlassian --env-file /absolute/path/atlassian.env --transport stdio
```

凭据文件字段与上游一致（值仅为占位示例）：

```dotenv
JIRA_URL=https://your-site.atlassian.net
JIRA_USERNAME=your-email@example.com
JIRA_API_TOKEN=your-own-token
CONFLUENCE_URL=https://your-site.atlassian.net/wiki
CONFLUENCE_USERNAME=your-email@example.com
CONFLUENCE_API_TOKEN=your-own-token
```

将文件放在仓库外并限制读取权限。配置支持 `mcpServers` 的客户端时：

```json
{
  "mcpServers": {
    "team-atlassian": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/absolute/path/mcp-atlassian",
        "--frozen",
        "mcp-atlassian",
        "--env-file", "/absolute/path/atlassian.env",
        "--transport", "stdio"
      ]
    }
  }
}
```

将原社区版 MCP 条目替换为团队版，避免两套相同工具重复注册。
若使用 `ENABLED_TOOLS` 白名单，加入 `jira_ensure_confluence_link`；
若使用 `TOOLSETS`，包含 `jira_links`。重启/重新连接客户端后检查 tools/list。

## 发布给团队

代码审查和测试通过后，将功能分支合并进 fork 的发布分支，再创建不可变版本标签。
以下 `v0.23.1+team.1` **仅为示例，尚未发布**：

```bash
git tag -a v0.23.1+team.1 -m 'Team release: verified Confluence page linking'
git push origin v0.23.1+team.1
```

同事可以通过已发布标签启动，无需发布到 PyPI：

```bash
uvx --from 'git+https://github.com/Gavin-Spotec/mcp-atlassian.git@v0.23.1+team.1' \
  mcp-atlassian --env-file /absolute/path/atlassian.env --transport stdio
```

更严格的版本固定可使用完整 Git commit SHA。Git 源码标签固定的是源码，
`uvx --from` 安装时的间接依赖未必使用仓库 `uv.lock`；如需完整复现依赖，
使用固定标签的本地 checkout + `uv sync --frozen` / `uv run --frozen`。
升级使用新标签，回滚改回旧标签，不覆盖已发布标签。

## 发布前验证

```bash
uv run pytest tests/unit/jira/test_links.py tests/unit/jira/test_confluence_links.py tests/unit/servers/test_confluence_link_tool.py
uv run python scripts/generate_tool_docs.py --check
```

在专用测试工单上依次验证：首次创建、再次调用返回 unchanged、普通 Web Link
被原地修复，以及 Jira 页面显示 Confluence 卡片。权限不足时应报错。
本地单元测试使用模拟 API，不能替代真实租户和 UI 验证。

需求发布 Skill 应优先调用实际工具名 `jira_ensure_confluence_link`，仅当返回
`verified=true` 时宣告 REST 关联完成；未连接此工具时明确说明缺失能力。
本次没有修改或分发团队外部的 Skill 文件。

## 官方接口依据

- [Atlassian 原生关联示例（其中 appId 格式不作为本工具前置条件）](https://support.atlassian.com/jira/kb/how-to-link-a-confluence-page-on-a-jira-cloud-issue-via-rest-api/)
- [Jira Remote Links REST API](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-remote-links/)
