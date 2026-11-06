# MCP Atlassian

本仓库是 [sooperset/mcp-atlassian](https://github.com/sooperset/mcp-atlassian) 的团队维护版，
保留上游 Jira、Confluence 工具，并新增 `jira_ensure_confluence_link`：提供 Jira 工单号和
Confluence 页面完整地址，即可创建、更新或复用 Jira → Confluence 原生关联，并读回验证结果。
该新增工具目前支持 Jira Cloud + Confluence Cloud，使用每位同事自己的凭据。

## 团队版安装（从 main 分支）

团队功能在功能分支开发，验证后合并并推送到本仓库的 `main`，同事统一从 `main` 安装。
以下配置需在相关功能合入远端 `main` 后使用。无需手动克隆仓库或发布到 PyPI；
直接运行 `uvx mcp-atlassian` 安装的是社区版，不包含本仓库新增功能。

### 1. 安装 uv 和 Git

macOS 默认不自带 uv。已安装 Homebrew 的同事可以执行：

```bash
brew install uv
```

也可以使用 [uv 官方安装脚本](https://docs.astral.sh/uv/getting-started/installation/)：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

安装 uv 后同时获得 `uvx`。重新打开终端，确认以下命令可用，并确保能够访问本 GitHub 仓库：

```bash
uv --version
uvx --version
git --version
```

如果尚未安装 Git，可以通过 Homebrew 执行 `brew install git`。

### 2. 准备个人凭据

在 [Atlassian 账号设置](https://id.atlassian.com/manage-profile/security/api-tokens)中创建 API Token，
在仓库外创建自己的 `atlassian.env` 文件，填写以下内容：

```dotenv
JIRA_URL=https://your-company.atlassian.net
JIRA_USERNAME=your.email@company.com
JIRA_API_TOKEN=your-own-token
CONFLUENCE_URL=https://your-company.atlassian.net/wiki
CONFLUENCE_USERNAME=your.email@company.com
CONFLUENCE_API_TOKEN=your-own-token
```

每个人使用自己的凭据，不要提交或共享该文件。macOS 下可用
`chmod 600 /absolute/path/atlassian.env` 限制文件读取权限。

### 3. 配置 MCP 客户端

支持 `mcpServers` JSON 配置的客户端可使用以下内容，将凭据文件路径改为本机绝对路径：

```json
{
  "mcpServers": {
    "team-atlassian": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Gavin-Spotec/mcp-atlassian.git@main",
        "mcp-atlassian",
        "--env-file",
        "/absolute/path/atlassian.env",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

首次启动会自动下载源码和依赖。已有社区版配置的同事应替换原来的 MCP 条目，
重新连接后确认工具列表包含 `jira_ensure_confluence_link`。
若设置了 `ENABLED_TOOLS` 白名单，需加入该工具；若设置了 `TOOLSETS`，需包含 `jira_links`。
客户端若找不到 `uvx`，可运行 `command -v uvx`，将输出的绝对路径填入 `command`。

也可以在终端直接启动：

```bash
uvx --from 'git+https://github.com/Gavin-Spotec/mcp-atlassian.git@main' \
  mcp-atlassian --env-file /absolute/path/atlassian.env --transport stdio
```

### 4. 更新团队版

`uvx` 会缓存运行环境，`main` 有新提交后可执行以下命令刷新，再重新连接 MCP 客户端：

```bash
uvx --refresh --from 'git+https://github.com/Gavin-Spotec/mcp-atlassian.git@main' \
  mcp-atlassian --help
```

参见 [uv 的缓存与版本说明](https://docs.astral.sh/uv/concepts/tools/#tool-versions)。
需要固定版本或回滚时，可将 `@main` 替换为已发布标签或完整 commit SHA；
更详细的功能行为、本地开发和标签发布方式见[团队使用指南](docs/team-confluence-link.md)。

## 上游项目介绍

以下徽章和社区版快速开始对应上游项目；安装本仓库团队版请使用上面的配置。

![PyPI Version](https://img.shields.io/pypi/v/mcp-atlassian)
![PyPI - Downloads](https://img.shields.io/pypi/dm/mcp-atlassian)
![PePy - Total Downloads](https://static.pepy.tech/personalized-badge/mcp-atlassian?period=total&units=international_system&left_color=grey&right_color=blue&left_text=Total%20Downloads)
[![Run Tests](https://github.com/sooperset/mcp-atlassian/actions/workflows/tests.yml/badge.svg)](https://github.com/sooperset/mcp-atlassian/actions/workflows/tests.yml)
![License](https://img.shields.io/github/license/sooperset/mcp-atlassian)
[![Docs](https://img.shields.io/badge/docs-mintlify-blue)](https://mcp-atlassian.soomiles.com)

Model Context Protocol (MCP) server for Atlassian products (Confluence and Jira). Supports both Cloud and Server/Data Center deployments.

https://github.com/user-attachments/assets/35303504-14c6-4ae4-913b-7c25ea511c3e

<details>
<summary>Confluence Demo</summary>

https://github.com/user-attachments/assets/7fe9c488-ad0c-4876-9b54-120b666bb785

</details>

## Quick Start

### 1. Get Your API Token

Go to https://id.atlassian.com/manage-profile/security/api-tokens and create a token.

> For Server/Data Center, use a Personal Access Token instead. See [Authentication](https://mcp-atlassian.soomiles.com/docs/authentication).

### 2. Configure Your IDE

Add to your Claude Desktop or Cursor MCP configuration:

```json
{
  "mcpServers": {
    "mcp-atlassian": {
      "command": "uvx",
      "args": ["mcp-atlassian"],
      "env": {
        "JIRA_URL": "https://your-company.atlassian.net",
        "JIRA_USERNAME": "your.email@company.com",
        "JIRA_API_TOKEN": "your_api_token",
        "CONFLUENCE_URL": "https://your-company.atlassian.net/wiki",
        "CONFLUENCE_USERNAME": "your.email@company.com",
        "CONFLUENCE_API_TOKEN": "your_api_token"
      }
    }
  }
}
```

> **Server/Data Center users**: Use `JIRA_PERSONAL_TOKEN` instead of `JIRA_USERNAME` + `JIRA_API_TOKEN`. See [Authentication](https://mcp-atlassian.soomiles.com/docs/authentication) for details.

#### Autohand Code

Use the same `uvx` server with your Atlassian credentials:

```bash
autohand mcp add mcp-atlassian env \
  JIRA_URL=https://your-company.atlassian.net \
  JIRA_USERNAME=your.email@company.com \
  JIRA_API_TOKEN=your_api_token \
  CONFLUENCE_URL=https://your-company.atlassian.net/wiki \
  CONFLUENCE_USERNAME=your.email@company.com \
  CONFLUENCE_API_TOKEN=your_api_token \
  uvx mcp-atlassian
```

Add `--scope project` after `add` to keep the configuration in the current
project. See [Autohand Code](https://github.com/autohandai/code-cli/) for current
installation and CLI details.

### 3. Start Using

Ask your AI assistant to:
- **"Find issues assigned to me in PROJ project"**
- **"Search Confluence for onboarding docs"**
- **"Create a bug ticket for the login issue"**
- **"Update the status of PROJ-123 to Done"**

## Documentation

Full documentation is available at **[mcp-atlassian.soomiles.com](https://mcp-atlassian.soomiles.com)**.

Documentation is also available in [llms.txt format](https://llmstxt.org/), which LLMs can consume easily:
- [`llms.txt`](https://mcp-atlassian.soomiles.com/llms.txt) — documentation sitemap
- [`llms-full.txt`](https://mcp-atlassian.soomiles.com/llms-full.txt) — complete documentation

| Topic | Description |
|-------|-------------|
| [Installation](https://mcp-atlassian.soomiles.com/docs/installation) | uvx, Docker, pip, from source |
| [Authentication](https://mcp-atlassian.soomiles.com/docs/authentication) | API tokens, PAT, OAuth 2.0 |
| [Configuration](https://mcp-atlassian.soomiles.com/docs/configuration) | IDE setup, environment variables |
| [HTTP Transport](https://mcp-atlassian.soomiles.com/docs/http-transport) | SSE, streamable-http, multi-user |
| [Tools Reference](https://mcp-atlassian.soomiles.com/docs/tools-reference) | All Jira & Confluence tools |
| [Troubleshooting](https://mcp-atlassian.soomiles.com/docs/troubleshooting) | Common issues & debugging |

## Compatibility

| Product | Deployment | Support |
|---------|------------|---------|
| Confluence | Cloud | Fully supported |
| Confluence | Server/Data Center | Supported (v6.0+) |
| Jira | Cloud | Fully supported |
| Jira | Server/Data Center | Supported (v8.14+) |

## Key Tools

| Jira | Confluence |
|------|------------|
| `jira_search` - Search with JQL | `confluence_search` - Search with CQL |
| `jira_get_issue` - Get issue details | `confluence_get_page` - Get page content |
| `jira_create_issue` - Create issues | `confluence_create_page` - Create pages |
| `jira_update_issue` - Update issues | `confluence_update_page` - Update pages |
| `jira_transition_issue` - Change status | `confluence_add_comment` - Add comments |

**99 tools total** — See [Tools Reference](https://mcp-atlassian.soomiles.com/docs/tools-reference) for the complete list.

## Security

Never share API tokens. Keep `.env` files secure. See [SECURITY.md](SECURITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup.

## License

MIT - See [LICENSE](LICENSE). Not an official Atlassian product.
