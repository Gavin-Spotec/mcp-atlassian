"""Regression coverage for native Confluence association and readback."""

from copy import deepcopy
from hashlib import sha256
from unittest.mock import Mock, create_autospec

import pytest
from atlassian.rest_client import AtlassianRestAPI
from requests.exceptions import ConnectionError, HTTPError, Timeout

from mcp_atlassian.exceptions import MCPAtlassianAuthenticationError
from mcp_atlassian.jira.links import LinksMixin, confluence_page_id

BASE = "https://test.atlassian.net/wiki"
URL = f"{BASE}/spaces/TEAM/pages/123/Plan"
CANONICAL = f"{BASE}/pages/viewpage.action?pageId=123"
LINK = {
    "id": 42,
    "globalId": f"confluence-page:{sha256(CANONICAL.encode()).hexdigest()}",
    "application": {"type": "com.atlassian.confluence", "name": "System Confluence"},
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
    links.jira.get.side_effect = [[], [LINK], [LINK]]
    first = invoke(links)
    second = invoke(links)
    assert (first["action"], second["action"]) == ("created", "unchanged")
    assert first["verified"] is True
    assert first["link_id"] == "42"
    payload = {k: v for k, v in LINK.items() if k != "id"}
    links.jira.post.assert_called_once_with(ENDPOINT, json=payload)
    links.jira.put.assert_not_called()


def test_update_native_link_preserves_id_summary_icon_and_status(links):
    old = {
        "id": 42,
        "application": deepcopy(LINK["application"]),
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
    expected.pop("globalId")
    expected["object"].update(
        {k: v for k, v in old["object"].items() if k not in ("url", "title")}
    )
    links.jira.get.side_effect = [[old], [expected]]
    assert invoke(links)["action"] == "updated"
    links.jira.put.assert_called_once_with(
        f"{ENDPOINT}/42", data={k: v for k, v in expected.items() if k != "id"}
    )
    links.jira.post.assert_not_called()
    assert old == snapshot


def test_equivalent_url_is_unchanged(links):
    existing = deepcopy(LINK)
    existing["object"]["url"] = URL
    links.jira.get.side_effect = [[existing]]
    assert invoke(links)["action"] == "unchanged"
    links.jira.post.assert_not_called()
    links.jira.put.assert_not_called()


@pytest.mark.parametrize("existing", [[LINK, LINK], None, {"error": "denied"}])
def test_ambiguous_or_malformed_links_do_not_create(links, existing):
    links.jira.get.side_effect = [existing]
    with pytest.raises(ValueError):
        invoke(links)
    links.jira.post.assert_not_called()
    links.jira.put.assert_not_called()


@pytest.mark.parametrize(
    "application_type,page_url",
    [
        ("foreign", URL),
        (None, URL),
        ("com.atlassian.confluence", f"{BASE}/pages/viewpage.action?pageId=456"),
    ],
)
def test_global_id_collision_rejects_mismatched_identity(
    links: LinksMixin, application_type: str | None, page_url: str
) -> None:
    existing = deepcopy(LINK)
    existing["application"] = {"type": application_type} if application_type else {}
    existing["object"]["url"] = page_url
    links.jira.get.side_effect = [[existing]]
    with pytest.raises(ValueError, match="globalId"):
        invoke(links)
    links.jira.put.assert_not_called()
    links.jira.post.assert_not_called()


def test_same_page_id_on_other_site_is_preserved(links):
    other = deepcopy(LINK)
    other.pop("globalId")
    other["object"]["url"] = "https://other.atlassian.net/wiki/spaces/T/pages/123"
    links.jira.get.side_effect = [[other], [other, LINK]]
    assert invoke(links)["action"] == "created"
    links.jira.put.assert_not_called()


@pytest.mark.parametrize(
    "error", [Timeout(), ConnectionError(), HTTPError(response=Mock(status_code=503))]
)
def test_uncertain_write_reads_back_without_retry(links, error):
    links.jira.get.side_effect = [[], [LINK]]
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
    links.jira.get.side_effect = [[], after]
    with pytest.raises(RuntimeError, match="[Ww]rite may have succeeded"):
        invoke(links)
    assert links.jira.post.call_count == 1


def test_update_readback_must_preserve_link_id(links):
    old = deepcopy(LINK)
    old["object"]["title"] = "Old title"
    links.jira.get.side_effect = [[old], [dict(LINK, id=99)]]
    with pytest.raises(RuntimeError, match="verification failed"):
        invoke(links)


@pytest.mark.parametrize("status", [401, 403])
def test_permission_denied_never_claims_success(links, status):
    links.jira.get.side_effect = [[]]
    links.jira.post.side_effect = HTTPError(response=Mock(status_code=status))
    with pytest.raises(MCPAtlassianAuthenticationError):
        invoke(links)
    assert links.jira.get.call_count == 1


def test_data_center_is_explicitly_unsupported(links):
    links.config.url = "https://jira.example.test"
    with pytest.raises(ValueError, match="Cloud"):
        invoke(links)
    links.jira.get.assert_not_called()


def test_path_injection_rejected(links):
    with pytest.raises(ValueError):
        links.ensure_confluence_link("../TEST-1", BASE, "123", "Plan")
    links.jira.get.assert_not_called()


@pytest.mark.parametrize("old_global_id", [None, "appId=legacy-app&pageId=123"])
def test_existing_native_identity_is_preserved(links, old_global_id):
    existing = deepcopy(LINK)
    if old_global_id is None:
        existing.pop("globalId")
    else:
        existing["globalId"] = old_global_id
    links.jira.get.side_effect = [[existing]]
    result = invoke(links)
    assert result["action"] == "unchanged"
    assert result["global_id"] == old_global_id
    links.jira.post.assert_not_called()
    links.jira.put.assert_not_called()


def test_old_global_id_is_preserved_during_title_update(links):
    existing = deepcopy(LINK)
    existing["globalId"] = "appId=legacy-app&pageId=123"
    existing["object"]["title"] = "Old title"
    after = deepcopy(existing)
    after["object"]["title"] = "Plan"
    links.jira.get.side_effect = [[existing], [after]]
    assert invoke(links)["action"] == "updated"
    assert links.jira.put.call_args.kwargs["data"]["globalId"] == existing["globalId"]


def test_creation_only_calls_issue_remote_link_endpoint(links):
    def read(path):
        assert path == ENDPOINT, "Must not query administrator application links"
        return [LINK] if links.jira.post.called else []

    links.jira.get.side_effect = read
    assert invoke(links)["verified"] is True
    assert links.jira.post.call_args.args == (ENDPOINT,)
    assert "appId=" not in links.jira.post.call_args.kwargs["json"]["globalId"]


def test_global_id_is_site_bound(links):
    other_base = "https://other.atlassian.net/wiki"
    other_url = f"{other_base}/pages/viewpage.action?pageId=123"
    other = deepcopy(LINK)
    other["object"]["url"] = other_url
    other["globalId"] = f"confluence-page:{sha256(other_url.encode()).hexdigest()}"
    links.jira.get.side_effect = [[LINK], [LINK, other]]
    result = links.ensure_confluence_link("TEST-1", other_base, "123", "Plan")
    assert result["action"] == "created"
    assert result["global_id"] != LINK["globalId"]


def test_no_global_id_does_not_match_other_pages_on_readback(links: LinksMixin) -> None:
    previous = deepcopy(LINK)
    previous.pop("globalId")
    previous["object"]["title"] = "Old title"
    after = deepcopy(LINK)
    after.pop("globalId")
    unrelated = deepcopy(LINK)
    unrelated.pop("globalId")
    unrelated["id"] = 99
    unrelated["object"]["url"] = f"{BASE}/pages/viewpage.action?pageId=456"
    links.jira.get.side_effect = [[previous, unrelated], [after, unrelated]]
    assert invoke(links)["action"] == "updated"
