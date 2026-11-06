"""MCP-facing contract for the Confluence linking tool."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastmcp import Client, FastMCP

from mcp_atlassian.servers.context import MainAppContext
from mcp_atlassian.servers.jira import jira_mcp


@pytest.fixture
def clients():
    jira = Mock()
    jira.config.is_cloud = True
    jira.ensure_confluence_link.return_value = {"verified": True, "action": "created"}
    confluence = Mock()
    confluence.config.is_cloud = True
    confluence.config.url = "https://test.atlassian.net/wiki"
    confluence.get_page_content.return_value = SimpleNamespace(
        id="123", title="Real page title", type="page", status="current"
    )
    return jira, confluence


@asynccontextmanager
async def connection(clients, read_only=False):
    @asynccontextmanager
    async def lifespan(server):
        yield {"app_lifespan_context": MainAppContext(read_only=read_only)}

    server = FastMCP("test", lifespan=lifespan)
    server.mount(jira_mcp, namespace="jira")
    with (
        patch(
            "mcp_atlassian.servers.jira.get_jira_fetcher",
            AsyncMock(return_value=clients[0]),
        ) as get_jira,
        patch(
            "mcp_atlassian.servers.jira.get_confluence_fetcher",
            AsyncMock(return_value=clients[1]),
        ) as get_confluence,
    ):
        async with Client(server) as client:
            yield client, get_jira, get_confluence


ARGS = {
    "issue_key": "TEST-1",
    "confluence_page_url": "https://test.atlassian.net/wiki/spaces/T/pages/123/Page",
}


@pytest.mark.anyio
async def test_public_tool_uses_current_request_clients_and_real_title(clients):
    async with connection(clients) as (client, get_jira, get_confluence):
        tools = {tool.name: tool for tool in await client.list_tools()}
        tool = tools["jira_ensure_confluence_link"]
        assert tool.annotations.idempotentHint is True
        result = await client.call_tool("jira_ensure_confluence_link", ARGS)
        assert json.loads(result.content[0].text)["verified"] is True
        get_jira.assert_awaited_once()
        get_confluence.assert_awaited_once()
    clients[0].ensure_confluence_link.assert_called_once_with(
        "TEST-1", "https://test.atlassian.net/wiki", "123", "Real page title"
    )


@pytest.mark.anyio
async def test_read_only_blocks_before_resolving_clients(clients):
    async with connection(clients, read_only=True) as (
        client,
        get_jira,
        get_confluence,
    ):
        result = await client.call_tool(
            "jira_ensure_confluence_link", ARGS, raise_on_error=False
        )
        assert result.is_error
        get_jira.assert_not_awaited()
        get_confluence.assert_not_awaited()
    clients[0].ensure_confluence_link.assert_not_called()


@pytest.mark.anyio
async def test_foreign_url_never_reads_page_or_writes_link(clients):
    async with connection(clients) as (client, _, __):
        result = await client.call_tool(
            "jira_ensure_confluence_link",
            dict(ARGS, confluence_page_url="https://evil.test/wiki/spaces/T/pages/123"),
            raise_on_error=False,
        )
        assert result.is_error
    clients[1].get_page_content.assert_not_called()
    clients[0].ensure_confluence_link.assert_not_called()


@pytest.mark.parametrize(
    "field,value", [("status", "draft"), ("type", "blogpost"), ("id", "456")]
)
@pytest.mark.anyio
async def test_unpublished_or_wrong_page_is_rejected(clients, field, value):
    setattr(clients[1].get_page_content.return_value, field, value)
    async with connection(clients) as (client, _, __):
        result = await client.call_tool(
            "jira_ensure_confluence_link", ARGS, raise_on_error=False
        )
        assert result.is_error
    clients[0].ensure_confluence_link.assert_not_called()
