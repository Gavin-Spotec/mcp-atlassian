"""Module for Jira issue link operations."""

import logging
import re
from copy import deepcopy
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qs, urlsplit

from requests.exceptions import ConnectionError, HTTPError, Timeout

from ..models.jira import JiraIssueLinkType
from ..utils.decorators import handle_auth_errors
from .client import JiraClient

logger = logging.getLogger("mcp-jira")


def confluence_page_id(url: str, base_url: str) -> str:
    """Extract a page ID only from a URL on the configured Confluence site.

    Supports Cloud /wiki/spaces/.../pages/ID and viewpage.action?pageId=ID.
    Short links are deliberately rejected; no user-supplied URL is fetched.
    """
    base = urlsplit(base_url)
    page = urlsplit(url)
    if (
        base.scheme != "https"
        or not base.hostname
        or base.username
        or base.password
        or base.query
        or base.fragment
        or base.path.rstrip("/") != "/wiki"
        or page.scheme != base.scheme
        or page.netloc.lower() != base.netloc.lower()
        or page.username
        or page.password
    ):
        raise ValueError("Use an HTTPS page URL on the configured Confluence site.")
    path = page.path
    match = re.fullmatch(r"/wiki/spaces/[^/]+/pages/([1-9][0-9]*)(?:/.*)?", path)
    if match:
        return match.group(1)
    if path == "/wiki/pages/viewpage.action":
        ids = parse_qs(page.query).get("pageId", [])
        if len(ids) == 1 and re.fullmatch(r"[1-9][0-9]*", ids[0]):
            return ids[0]
    raise ValueError("Use a full Confluence page URL containing a numeric page ID.")


class LinksMixin(JiraClient):
    """Mixin for Jira issue link operations."""

    @handle_auth_errors("Jira API")
    def get_issue_link_types(self) -> list[JiraIssueLinkType]:
        """
        Get all available issue link types.

        Returns:
            List of JiraIssueLinkType objects

        Raises:
            MCPAtlassianAuthenticationError: If authentication fails
                with the Jira API (401/403)
            Exception: If there is an error retrieving issue link types
        """
        try:
            link_types_response = self.jira.get("rest/api/2/issueLinkType")
            if not isinstance(link_types_response, dict):
                msg = (
                    "Unexpected return value type from "
                    f"`jira.get`: {type(link_types_response)}"
                )
                logger.error(msg)
                raise TypeError(msg)

            link_types_data = link_types_response.get("issueLinkTypes", [])

            return [
                JiraIssueLinkType.from_api_response(link_type)
                for link_type in link_types_data
            ]
        except HTTPError:
            raise  # let decorator handle auth errors
        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"Error getting issue link types: {error_msg}",
                exc_info=True,
            )
            raise Exception(f"Error getting issue link types: {error_msg}") from e

    def _enforce_internal_only_link_comment(
        self, inward_key: str, outward_key: str
    ) -> None:
        """Reject link comments touching JIRA_INTERNAL_ONLY_PROJECTS projects.

        A link comment is a standard Jira comment posted on one of the
        linked issues, with no reliable way to force it internal on JSM.
        The check deliberately errs safe by rejecting when EITHER side of
        the link is a listed project (rather than resolving which side
        Jira will attach the comment to): a false reject costs one extra
        call, a false accept is a customer-visible leak.

        Args:
            inward_key: The inward issue key (e.g. 'CC-123')
            outward_key: The outward issue key (e.g. 'PROJ-456')

        Raises:
            ValueError: If either issue's project is listed in
                JIRA_INTERNAL_ONLY_PROJECTS
        """
        for key in (inward_key, outward_key):
            if self._is_internal_only_project(key):
                raise ValueError(
                    f"Issue {key} belongs to a project configured as "
                    "internal-only (JIRA_INTERNAL_ONLY_PROJECTS). Link "
                    "comments are posted via the core Jira API and may "
                    "be customer-visible on JSM, with no way to force "
                    "them internal from this call — so they are blocked "
                    "here. Create the link WITHOUT a comment, then post "
                    "an internal note with add_comment(public=False) on "
                    "the relevant issue."
                )

    @handle_auth_errors("Jira API")
    def create_issue_link(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Create a link between two issues.

        Args:
            data: A dictionary containing the link data with the
                following structure:
                {
                    "type": {"name": "Duplicate" },
                    "inwardIssue": { "key": "ISSUE-1"},
                    "outwardIssue": {"key": "ISSUE-2"},
                    "comment": {
                        "body": "Linked related issue!",
                        "visibility": {
                            "type": "group",
                            "value": "jira-software-users"
                        }
                    }
                }

        Returns:
            Dictionary with the created link information

        Raises:
            ValueError: If required fields are missing, or if a comment
                is included and either linked issue belongs to a project
                listed in JIRA_INTERNAL_ONLY_PROJECTS
            MCPAtlassianAuthenticationError: If authentication fails
                with the Jira API (401/403)
            Exception: If there is an error creating the issue link
        """
        # Validate required fields
        if not data.get("type"):
            raise ValueError("Link type is required")
        if not data.get("inwardIssue") or not data["inwardIssue"].get("key"):
            raise ValueError("Inward issue key is required")
        if not data.get("outwardIssue") or not data["outwardIssue"].get("key"):
            raise ValueError("Outward issue key is required")

        if data.get("comment"):
            self._enforce_internal_only_link_comment(
                data["inwardIssue"]["key"], data["outwardIssue"]["key"]
            )

        try:
            # Create the issue link
            self.jira.create_issue_link(data)

            # Return a response with the link information
            inward = data["inwardIssue"]["key"]
            outward = data["outwardIssue"]["key"]
            return {
                "success": True,
                "message": (f"Link created between {inward} and {outward}"),
                "link_type": data["type"]["name"],
                "inward_issue": inward,
                "outward_issue": outward,
            }
        except HTTPError:
            raise  # let decorator handle auth errors
        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"Error creating issue link: {error_msg}",
                exc_info=True,
            )
            raise Exception(f"Error creating issue link: {error_msg}") from e

    @handle_auth_errors("Jira API")
    def create_remote_issue_link(
        self, issue_key: str, link_data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Create a remote issue link (web link or Confluence link).

        Args:
            issue_key: The key of the issue (e.g., 'PROJ-123')
            link_data: Remote link data dict with structure:
                {
                    "object": {
                        "url": "https://example.com/page",
                        "title": "Example Page",
                        "summary": "Optional description",
                        "icon": {
                            "url16x16": "https://example.com/icon16.png",
                            "title": "Icon Title"
                        }
                    },
                    "relationship": "causes"
                }

        Returns:
            Dictionary with the created remote link information

        Raises:
            ValueError: If required fields are missing
            MCPAtlassianAuthenticationError: If authentication fails
                with the Jira API (401/403)
            Exception: If there is an error creating the link
        """
        # Validate required fields
        if not issue_key:
            raise ValueError("Issue key is required")
        if not link_data.get("object"):
            raise ValueError("Link object is required")
        if not link_data["object"].get("url"):
            raise ValueError("URL is required in link object")
        if not link_data["object"].get("title"):
            raise ValueError("Title is required in link object")

        try:
            # Cloud uses v3 API, Server/DC uses v2 API
            if self.config.is_cloud:
                endpoint = f"rest/api/3/issue/{issue_key}/remotelink"
            else:
                endpoint = f"rest/api/2/issue/{issue_key}/remotelink"
            self.jira.post(endpoint, json=link_data)

            return {
                "success": True,
                "message": (f"Remote link created for issue {issue_key}"),
                "issue_key": issue_key,
                "link_title": link_data["object"]["title"],
                "link_url": link_data["object"]["url"],
                "relationship": link_data.get("relationship", ""),
            }
        except HTTPError:
            raise  # let decorator handle auth errors
        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"Error creating remote issue link: {error_msg}",
                exc_info=True,
            )
            raise Exception(f"Error creating remote issue link: {error_msg}") from e

    @handle_auth_errors("Jira API")
    def get_remote_issue_links(self, issue_key: str) -> list[dict[str, Any]]:
        """Get remote links (web links, Confluence links) for an issue.

        Args:
            issue_key: The issue key (e.g., 'PROJ-123')

        Returns:
            List of remote link data dictionaries

        Raises:
            MCPAtlassianAuthenticationError: If authentication fails
        """
        try:
            if self.config.is_cloud:
                endpoint = f"rest/api/3/issue/{issue_key}/remotelink"
            else:
                endpoint = f"rest/api/2/issue/{issue_key}/remotelink"
            result = self.jira.get(endpoint)
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                return result.get("remoteLinks", [result])
            return []
        except HTTPError:
            raise  # let decorator handle auth errors
        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"Error getting remote links for {issue_key}: {error_msg}",
                exc_info=True,
            )
            msg = f"Error getting remote links for {issue_key}: {error_msg}"
            raise Exception(msg) from e

    @handle_auth_errors("Jira API")
    def ensure_confluence_link(
        self, issue_key: str, base_url: str, page_id: str, title: str
    ) -> dict[str, Any]:
        """Create, update or reuse a native Confluence remote link on Jira Cloud.

        Args:
            issue_key: Jira issue key.
            base_url: Configured Confluence URL, including /wiki.
            page_id: Page ID already read and verified through Confluence.
            title: Current title read from Confluence, not supplied by the model.

        Returns:
            Verified link ID and action (created, updated, unchanged, reconciled).
            Verification covers REST data, not Jira's UI rendering.

        Raises:
            ValueError: Unsupported deployment, ambiguous links or invalid metadata.
            RuntimeError: Write outcome or readback could not be verified.
            MCPAtlassianAuthenticationError: Jira denies access.
        """
        if not self.config.is_cloud:
            raise ValueError("Native Confluence linking currently supports Jira Cloud.")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*-[1-9][0-9]*", issue_key):
            raise ValueError("A valid Jira Cloud issue key is required.")
        if not re.fullmatch(r"[1-9][0-9]*", page_id) or not title.strip():
            raise ValueError("Verified Confluence page ID and title are required.")
        url = f"{base_url.rstrip('/')}/pages/viewpage.action?pageId={page_id}"
        confluence_page_id(url, base_url)
        # globalId 是调用方定义的可选去重标识，不依赖管理员应用链接接口。
        # 固定长度散列同时覆盖站点和页面 ID，避免不同租户的同号页面互相覆盖。
        global_id: str | None = f"confluence-page:{sha256(url.encode()).hexdigest()}"
        endpoint = f"rest/api/3/issue/{issue_key}/remotelink"

        def read_candidates() -> list[dict[str, Any]]:
            # 读取失败或结构异常不能当作“没有链接”，否则会重复创建。
            links: Any = self.jira.get(endpoint)
            if not isinstance(links, list) or any(
                not isinstance(link, dict) for link in links
            ):
                raise ValueError("Unexpected Jira remote links response.")
            matches = []
            for link in links:
                obj = link.get("object") or {}
                address = obj.get("url") if isinstance(obj, dict) else None
                same_page = False
                if isinstance(address, str):
                    try:
                        same_page = confluence_page_id(address, base_url) == page_id
                    except ValueError:
                        pass
                application = link.get("application") or {}
                is_confluence = (
                    isinstance(application, dict)
                    and application.get("type") == "com.atlassian.confluence"
                )
                # POST 会按 globalId 更新，先核对应用类型和页面身份，避免误覆盖。
                if global_id and link.get("globalId") == global_id:
                    if not is_confluence or not same_page:
                        raise ValueError(
                            "The globalId is already used by another link."
                        )
                if is_confluence and same_page:
                    matches.append(link)
            if len(matches) > 1:
                raise ValueError("Multiple native Confluence links match this page.")
            return matches

        candidates = read_candidates()
        previous = candidates[0] if candidates else None
        application = (previous or {}).get("application") or {}
        # 原有关联可能没有 globalId，也可能使用旧的 appId 格式；均保留其身份。
        # 按现有 link ID 更新，不为已经正确的关联额外写入或生成重复链接。
        if previous:
            global_id = previous.get("globalId") or None
            if global_id is not None and not isinstance(global_id, str):
                raise ValueError("Existing page link has an invalid globalId.")
        app_name = application.get("name") or "System Confluence"
        # Jira 的 PUT 会清空遗漏字段，保留原链接的摘要、图标和状态等数据。
        payload: dict[str, Any] = {
            "application": {
                **deepcopy((previous or {}).get("application") or {}),
                "type": "com.atlassian.confluence",
                "name": app_name,
            },
            "relationship": "Wiki Page",
            "object": {
                **deepcopy((previous or {}).get("object") or {}),
                "url": url,
                "title": title,
            },
        }

        if global_id is not None:
            payload["globalId"] = global_id

        def verified(link: dict[str, Any]) -> bool:
            obj = link.get("object") or {}
            application = link.get("application") or {}
            if not isinstance(obj, dict) or not isinstance(application, dict):
                return False
            try:
                same_page = confluence_page_id(obj.get("url", ""), base_url) == page_id
            except ValueError:
                same_page = False
            return bool(
                str(link.get("id", "")).isdigit()
                and link.get("globalId") == global_id
                and application.get("type") == "com.atlassian.confluence"
                and application.get("name") == app_name
                and link.get("relationship") == "Wiki Page"
                and obj.get("title") == title
                and same_page
                and (previous is None or str(link["id"]) == str(previous.get("id")))
            )

        def result(action: str, link: dict[str, Any]) -> dict[str, Any]:
            return {
                "success": True,
                "verified": True,
                "verification": "jira_remote_link_readback",
                "action": action,
                "issue_key": issue_key,
                "page_id": page_id,
                "link_id": str(link["id"]),
                "global_id": global_id,
                "page_url": url,
            }

        if previous and verified(previous):
            return result("unchanged", previous)
        action = "updated" if previous else "created"
        uncertain = False
        try:
            if previous:
                link_id = str(previous.get("id", ""))
                if not link_id.isdigit():
                    raise ValueError("Existing Jira remote link has no valid ID.")
                self.jira.put(f"{endpoint}/{link_id}", data=payload)
            else:
                # globalId 使服务端按同一页面执行 upsert；并发调用也使用相同标识。
                self.jira.post(endpoint, json=payload)
        except (Timeout, ConnectionError):
            uncertain = True
        except HTTPError as exc:
            if exc.response is None or exc.response.status_code < 500:
                raise
            uncertain = True
        # 超时或服务端错误后先读回，不盲目重发写请求，也不凭 HTTP 2xx 报成功。
        try:
            after = read_candidates()
        except (ValueError, HTTPError, Timeout, ConnectionError) as exc:
            raise RuntimeError(
                "Write may have succeeded, but readback failed. "
                "Inspect the issue links before retrying."
            ) from exc
        if len(after) != 1 or not verified(after[0]):
            raise RuntimeError(
                "Confluence link verification failed; write may have succeeded. "
                "Inspect the issue links before retrying."
            )
        return result("reconciled" if uncertain else action, after[0])

    @handle_auth_errors("Jira API")
    def remove_issue_link(self, link_id: str) -> dict[str, Any]:
        """
        Remove a link between two issues.

        Args:
            link_id: The ID of the link to remove

        Returns:
            Dictionary with the result of the operation

        Raises:
            ValueError: If link_id is empty
            MCPAtlassianAuthenticationError: If authentication fails
                with the Jira API (401/403)
            Exception: If there is an error removing the issue link
        """
        # Validate input
        if not link_id:
            raise ValueError("Link ID is required")
        # The ID becomes a URL path segment of a DELETE request; anything but
        # digits (e.g. "../issue/PROJ-1") could retarget the DELETE.
        if not link_id.isascii() or not link_id.isdecimal():
            raise ValueError("Link ID must contain only ASCII digits")

        try:
            self.jira.remove_issue_link(link_id)

            return {
                "success": True,
                "message": (f"Link with ID {link_id} has been removed"),
                "link_id": link_id,
            }
        except HTTPError:
            raise  # let decorator handle auth errors
        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"Error removing issue link: {error_msg}",
                exc_info=True,
            )
            raise Exception(f"Error removing issue link: {error_msg}") from e
