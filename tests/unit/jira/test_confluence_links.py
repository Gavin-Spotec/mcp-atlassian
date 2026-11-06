"""Regression coverage for native Confluence association and readback."""

from copy import deepcopy
from unittest.mock import Mock, create_autospec

import pytest
from atlassian.rest_client import AtlassianRestAPI
from requests.exceptions import ConnectionError, HTTPError, Timeout

from mcp_atlassian.exceptions import MCPAtlassianAuthenticationError
from mcp_atlassian.jira.links import LinksMixin, confluence_page_id

BASE = "https://test.atlassian.net/wiki"
URL = f"{BASE}/spaces/TEAM/pages/123/Plan"
CANONICAL = f"{BASE}/pages/viewpage.action?pageId=123"
APP = {
    "id": "actual-app-id",
    "name": "System Confluence",
    "type": "confluence",
    "displayUrl": BASE,
}
LINK = {
    "id": 42,
    "globalId": "appId=actual-app-id&pageId=123",
    "application": {"type": "com.atlassian.confluence", "name": APP["name"]},
    "relationship": "Wiki Page",
    "object": {"url": CANONICAL, "title": "Plan"},
}
ENDPOINT = "rest/api/3/issue/TEST-1/remotelink"


@pytest.fixture
def links(mock_config, mock_atlassian_jira):
    client = LinksMixin(config=mock_config)
    client.jira = mock_atlassian_jira
    return client


def invoke(links):
    return links.ensure_confluence_link("TEST-1", BASE, "123", "Plan")


@pytest.mark.parametrize("url", [URL, CANONICAL, URL + "?source=copy#section"])
def test_supported_url(url):
    assert confluence_page_id(url, BASE) == "123"


@pytest.mark.parametrize(
    "url",
    [
        "https://other.atlassian.net/wiki/spaces/TEAM/pages/123/Plan",
        "https://test.atlassian.net.evil.test/wiki/spaces/TEAM/pages/123/Plan",
        "https://user@test.atlassian.net/wiki/spaces/TEAM/pages/123/Plan",
        "http://test.atlassian.net/wiki/spaces/TEAM/pages/123/Plan",
        f"{BASE}/x/short",
        f"{BASE}/pages/viewpage.action?pageId=123&pageId=456",
        f"{BASE}/spaces/TEAM/pages/123evil",
        f"{BASE}/spaces/TEAM/pages/0/Plan",
        "not a URL",
    ],
)
def test_invalid_url(url):
    with pytest.raises(ValueError):
        confluence_page_id(url, BASE)


def test_create_and_repeat_without_second_write(links):
    links.jira.get.side_effect = [[APP], [], [LINK], [APP], [LINK]]
    first = invoke(links)
    second = invoke(links)
    assert (first["action"], second["action"]) == ("created", "unchanged")
    assert first["verified"] is True
    assert first["link_id"] == "42"
    payload = {k: v for k, v in LINK.items() if k != "id"}
    links.jira.post.assert_called_once_with(ENDPOINT, json=payload)
    links.jira.put.assert_not_called()


def test_repair_web_link_preserves_id_summary_icon_and_status(links):
    old = {
        "id": 42,
        "application": {},
        "object": {
            "url": URL,
            "title": "Old title",
            "summary": "Keep this",
            "icon": {"url16x16": "https://example.test/icon"},
            "status": {"resolved": True},
        },
    }
    links.jira.put = create_autospec(AtlassianRestAPI, instance=True).put
    snapshot = deepcopy(old)
    expected = deepcopy(LINK)
    expected["object"].update(
        {k: v for k, v in old["object"].items() if k not in ("url", "title")}
    )
    links.jira.get.side_effect = [[APP], [old], [expected]]
    assert invoke(links)["action"] == "updated"
    links.jira.put.assert_called_once_with(
        f"{ENDPOINT}/42", data={k: v for k, v in expected.items() if k != "id"}
    )
    links.jira.post.assert_not_called()
    assert old == snapshot


def test_equivalent_url_is_unchanged(links):
    existing = deepcopy(LINK)
    existing["object"]["url"] = URL
    links.jira.get.side_effect = [[APP], [existing]]
    assert invoke(links)["action"] == "unchanged"
    links.jira.post.assert_not_called()
    links.jira.put.assert_not_called()


@pytest.mark.parametrize("apps", [[], [APP, APP], {}, [dict(APP, id=None)]])
def test_missing_ambiguous_or_invalid_app_fails_without_write(links, apps):
    links.jira.get.return_value = apps
    with pytest.raises(ValueError):
        invoke(links)
    links.jira.post.assert_not_called()
    links.jira.put.assert_not_called()


def test_other_site_app_cannot_match(links):
    links.jira.get.return_value = [dict(APP, displayUrl="https://other.test/wiki")]
    with pytest.raises(ValueError, match="exactly one"):
        invoke(links)
    links.jira.post.assert_not_called()


@pytest.mark.parametrize("existing", [[LINK, LINK], None, {"error": "denied"}])
def test_ambiguous_or_malformed_links_do_not_create(links, existing):
    links.jira.get.side_effect = [[APP], existing]
    with pytest.raises(ValueError):
        invoke(links)
    links.jira.post.assert_not_called()
    links.jira.put.assert_not_called()


@pytest.mark.parametrize(
    "field,value", [("globalId", "foreign-id"), ("application", {"type": "foreign"})]
)
def test_conflicting_identity_fails(links, field, value):
    existing = deepcopy(LINK)
    existing[field] = value
    links.jira.get.side_effect = [[APP], [existing]]
    with pytest.raises(ValueError):
        invoke(links)
    links.jira.put.assert_not_called()
    links.jira.post.assert_not_called()


def test_same_page_id_on_other_site_is_not_repaired(links):
    other = deepcopy(LINK)
    other.pop("globalId")
    other["object"]["url"] = "https://other.atlassian.net/wiki/spaces/T/pages/123"
    links.jira.get.side_effect = [[APP], [other], [other, LINK]]
    assert invoke(links)["action"] == "created"
    links.jira.put.assert_not_called()


@pytest.mark.parametrize(
    "error", [Timeout(), ConnectionError(), HTTPError(response=Mock(status_code=503))]
)
def test_uncertain_write_reads_back_without_retry(links, error):
    links.jira.get.side_effect = [[APP], [], [LINK]]
    links.jira.post.side_effect = error
    result = invoke(links)
    assert result["action"] == "reconciled"
    assert result["verified"] is True
    assert links.jira.post.call_count == 1


@pytest.mark.parametrize(
    "after",
    [[], [dict(LINK, application={})], [dict(LINK, globalId="wrong")], Timeout()],
)
def test_successful_write_without_verified_readback_is_failure(links, after):
    links.jira.get.side_effect = [[APP], [], after]
    with pytest.raises(RuntimeError, match="[Ww]rite may have succeeded"):
        invoke(links)
    assert links.jira.post.call_count == 1


def test_update_readback_must_preserve_link_id(links):
    old = deepcopy(LINK)
    old["application"] = {}
    links.jira.get.side_effect = [[APP], [old], [dict(LINK, id=99)]]
    with pytest.raises(RuntimeError, match="verification failed"):
        invoke(links)


@pytest.mark.parametrize("status", [401, 403])
def test_permission_denied_never_claims_success(links, status):
    links.jira.get.side_effect = [[APP], []]
    links.jira.post.side_effect = HTTPError(response=Mock(status_code=status))
    with pytest.raises(MCPAtlassianAuthenticationError):
        invoke(links)
    assert links.jira.get.call_count == 2


def test_data_center_is_explicitly_unsupported(links):
    links.config.url = "https://jira.example.test"
    with pytest.raises(ValueError, match="Cloud"):
        invoke(links)
    links.jira.get.assert_not_called()


def test_path_injection_rejected(links):
    with pytest.raises(ValueError):
        links.ensure_confluence_link("../TEST-1", BASE, "123", "Plan")
    links.jira.get.assert_not_called()


def admin_mapping():
    import json

    return json.dumps(
        {
            "jira_url": "https://test.atlassian.net",
            "confluence_url": BASE,
            "app_id": APP["id"],
            "app_name": APP["name"],
        }
    )


def test_admin_mapping_avoids_admin_endpoint_but_still_verifies(links):
    links.config.confluence_app_link = admin_mapping()
    links.jira.url = links.config.url
    links.jira.get.side_effect = [[], [LINK]]
    result = invoke(links)
    assert result["application_id_source"] == "administrator_configuration"
    assert result["verified"] is True
    assert [call.args[0] for call in links.jira.get.call_args_list] == [
        ENDPOINT,
        ENDPOINT,
    ]


@pytest.mark.parametrize("mapping", ["not json", "[]", "{}", '{"app_id":"fake"}'])
def test_bad_admin_mapping_never_writes(links, mapping):
    links.config.confluence_app_link = mapping
    with pytest.raises(ValueError):
        invoke(links)
    links.jira.post.assert_not_called()
    links.jira.get.assert_not_called()


@pytest.mark.parametrize(
    "changed", ["jira_config", "jira_transport", "confluence", "oauth"]
)
def test_admin_mapping_is_bound_to_both_sites(links, changed):
    links.config.confluence_app_link = admin_mapping()
    links.jira.url = links.config.url
    base = BASE
    if changed == "jira_config":
        links.config.url = "https://other.atlassian.net"
    elif changed == "jira_transport":
        links.jira.url = "https://other.atlassian.net"
    elif changed == "confluence":
        base = "https://other.atlassian.net/wiki"
    else:
        links.config.auth_type = "oauth"
    with pytest.raises(ValueError):
        links.ensure_confluence_link("TEST-1", base, "123", "Plan")
    links.jira.get.assert_not_called()
    links.jira.post.assert_not_called()


def test_discovery_denied_has_actionable_error(links):
    links.jira.get.side_effect = HTTPError(response=Mock(status_code=403))
    with pytest.raises(ValueError, match="JIRA_CONFLUENCE_APP_LINK"):
        invoke(links)
    links.jira.post.assert_not_called()


def test_config_reads_admin_mapping_from_env(monkeypatch):
    from mcp_atlassian.jira.config import JiraConfig

    monkeypatch.setenv("JIRA_URL", "https://test.atlassian.net")
    monkeypatch.setenv("JIRA_USERNAME", "test@example.test")
    monkeypatch.setenv("JIRA_API_TOKEN", "placeholder")
    monkeypatch.setenv("JIRA_CONFLUENCE_APP_LINK", admin_mapping())
    assert JiraConfig.from_env().confluence_app_link == admin_mapping()
