import base64
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import httpx

from core.config import JiraConfig
from utils.logger import get_logger

logger = get_logger("jira_client")


class JiraApiError(Exception):
    """Custom exception for Jira API errors with status and response details."""

    def __init__(self, status_code: int, message: str, detail: Optional[str] = None):
        super().__init__(f"Jira API Error [{status_code}]: {message}")
        self.status_code = status_code
        self.detail = detail


class JiraClient:
    """Client for interacting with Jira Cloud REST API v3."""

    def __init__(self, config: JiraConfig):
        self.config = config
        self.base_url = config.clean_base_url
        self.email = config.email
        self.api_token = config.api_token
        self._auth_header = self._build_auth_header()
        self.cloud_id: Optional[str] = self._resolve_cloud_id()
        if self.cloud_id:
            self.api_url: str = f"https://api.atlassian.com/ex/jira/{self.cloud_id}"
        else:
            self.api_url: str = self.base_url

    def _build_auth_header(self) -> Dict[str, str]:
        """Generates Basic Auth header from email and API token."""
        raw = f"{self.email}:{self.api_token}".encode("utf-8")
        encoded = base64.b64encode(raw).decode("utf-8")
        return {
            "Authorization": f"Basic {encoded}",
            "Accept": "application/json",
            "User-Agent": "JiraSyncTicket/1.0",
        }

    def _resolve_cloud_id(self) -> Optional[str]:
        """Auto-resolves Atlassian cloudId from tenant_info for Cloud instances."""
        if ".atlassian.net" in self.base_url:
            try:
                with httpx.Client(timeout=8.0) as client:
                    res = client.get(f"{self.base_url}/_edge/tenant_info")
                    if res.status_code == 200:
                        cid = res.json().get("cloudId")
                        logger.debug(f"Resolved Jira cloudId: {cid}")
                        return cid
            except Exception as e:
                logger.debug(f"Could not resolve tenant_info cloudId: {e}")
        return None

    def verify_account(self) -> Dict[str, Any]:
        """Validates credentials via direct tenant URL or Atlassian Platform Gateway."""
        logger.debug(f"Verifying account for user {self.email}")

        # 1. Try direct URL first
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.get(f"{self.base_url}/rest/api/3/myself", headers=self._auth_header)
                if res.status_code == 200:
                    data = res.json()
                    self.api_url = self.base_url
                    logger.info(
                        f"Account verified directly: {data.get('displayName')} ({data.get('emailAddress', self.email)})"
                    )
                    return data
        except Exception as e:
            logger.debug(f"Direct verification check error: {e}")

        # 2. If direct fails or returns 401, check if this is a Scoped API Token needing the Gateway
        if self.cloud_id:
            gateway_url = f"https://api.atlassian.com/ex/jira/{self.cloud_id}"
            logger.info(f"Checking via Atlassian Platform Gateway: {gateway_url}")
            try:
                with httpx.Client(timeout=15.0) as client:
                    # Check permissions on gateway
                    r_perm = client.get(
                        f"{gateway_url}/rest/api/3/mypermissions",
                        headers=self._auth_header,
                        params={"permissions": "BROWSE_PROJECTS"},
                    )
                    if r_perm.status_code == 200:
                        self.api_url = gateway_url
                        logger.info("Scoped API Token verified successfully via Atlassian Gateway!")

                        # Try to get displayName if read:jira-user scope is also available
                        r_self = client.get(f"{gateway_url}/rest/api/3/myself", headers=self._auth_header)
                        if r_self.status_code == 200:
                            return r_self.json()

                        # Return synthesized user dict when myself is restricted
                        display_name = self.email.split("@")[0].replace(".", " ").title()
                        return {
                            "displayName": f"{display_name} (Scoped Token)",
                            "emailAddress": self.email,
                            "accountId": self.email,
                            "active": True,
                        }
            except Exception as e:
                logger.error(f"Gateway verification failed: {e}", exc_info=True)

        # 3. Failed all attempts
        logger.error("Authentication failed: Invalid email or API token on both direct and gateway endpoints (401)")
        raise JiraApiError(401, "Invalid Jira email or API token, or token lacks required scopes.")

    def check_permissions(self, permission_keys: Optional[List[str]] = None) -> Dict[str, bool]:
        """Checks whether the authenticated user holds required permissions.

        Returns a dictionary mapping permission_key to boolean (havePermission).
        """
        if permission_keys is None:
            permission_keys = ["BROWSE_PROJECTS"]

        params = {"permissions": ",".join(permission_keys)}
        url = f"{self.api_url}/rest/api/3/mypermissions"
        logger.debug(f"Checking permissions {permission_keys} at {url}")

        results: Dict[str, bool] = {key: False for key in permission_keys}
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.get(url, headers=self._auth_header, params=params)
                if res.status_code == 200:
                    data = res.json()
                    perms = data.get("permissions", {})
                    for key in permission_keys:
                        info = perms.get(key, {})
                        results[key] = info.get("havePermission", False)
                    logger.info(f"Permission check results: {results}")
                    return results
                else:
                    logger.warning(
                        f"Permission check returned {res.status_code}: {res.text}. Proceeding with caution."
                    )
                    return results
        except Exception as e:
            logger.warning(f"Failed to check permissions via API: {e}", exc_info=True)
            return results

    def get_issue(self, issue_key: str) -> Dict[str, Any]:
        """Fetches complete issue details including changelog and attachments with endpoint fallback."""
        key = issue_key.strip().upper()
        params = {"expand": "changelog,names"}

        # Candidate URLs to try (primary api_url first, then fallback if needed)
        urls_to_try = [f"{self.api_url}/rest/api/3/issue/{key}"]
        if self.cloud_id:
            gw_url = f"https://api.atlassian.com/ex/jira/{self.cloud_id}/rest/api/3/issue/{key}"
            direct_url = f"{self.base_url}/rest/api/3/issue/{key}"
            if gw_url not in urls_to_try:
                urls_to_try.append(gw_url)
            if direct_url not in urls_to_try:
                urls_to_try.append(direct_url)

        last_status = 404
        last_error = f"Ticket '{key}' was not found on Jira."

        for url in urls_to_try:
            logger.info(f"Fetching issue {key} from {url}")
            try:
                with httpx.Client(timeout=25.0) as client:
                    res = client.get(url, headers=self._auth_header, params=params)
                    if res.status_code == 200:
                        logger.info(f"Successfully retrieved ticket {key}")
                        return res.json()
                    elif res.status_code in (401, 403, 404):
                        last_status = res.status_code
                        last_error = res.text
                        logger.debug(f"Attempt on {url} returned {res.status_code}, trying next candidate if available...")
                    else:
                        last_status = res.status_code
                        last_error = res.text
            except httpx.RequestError as e:
                logger.debug(f"Network error on {url}: {e}")

        if last_status == 404:
            logger.error(f"Ticket {key} was not found (404)")
            raise JiraApiError(404, f"Ticket '{key}' was not found on Jira.")
        elif last_status == 403:
            logger.error(f"Access denied to ticket {key} (403)")
            raise JiraApiError(403, f"Access denied for ticket '{key}' (403 Forbidden).")
        elif last_status == 401:
            logger.error("Authentication expired or invalid during issue fetch")
            raise JiraApiError(401, "Authentication expired or invalid while fetching ticket.")
        else:
            logger.error(f"Error fetching issue {key}: {last_status} - {last_error}")
            raise JiraApiError(last_status, f"Jira API error: {last_error}")

    def download_attachment(self, content_url: str, dest_path: Path) -> bool:
        """Downloads an attachment file if it does not exceed the size limit.

        Returns True on success, False otherwise.
        """
        logger.debug(f"Downloading attachment from {content_url} to {dest_path}")
        max_bytes = self.config.max_asset_size_mb * 1024 * 1024

        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                # Jira Cloud attachment URLs require Basic Auth or redirect to authenticated S3/Cloudfront
                with client.stream("GET", content_url, headers=self._auth_header) as response:
                    if response.status_code != 200:
                        logger.warning(
                            f"Failed to download asset {content_url}: HTTP {response.status_code}"
                        )
                        return False

                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > max_bytes:
                        logger.warning(
                            f"Skipping asset {dest_path.name}: size {content_length} bytes exceeds limit of {max_bytes} bytes"
                        )
                        return False

                    downloaded = 0
                    with open(dest_path, "wb") as f:
                        for chunk in response.iter_bytes(chunk_size=16384):
                            downloaded += len(chunk)
                            if downloaded > max_bytes:
                                logger.warning(
                                    f"Aborted asset {dest_path.name}: downloaded exceeded limit"
                                )
                                f.close()
                                if dest_path.exists():
                                    dest_path.unlink()
                                return False
                            f.write(chunk)

            logger.info(f"Asset downloaded successfully: {dest_path.name} ({downloaded} bytes)")
            return True
        except Exception as e:
            logger.error(f"Error downloading attachment {dest_path.name}: {e}", exc_info=True)
            if dest_path.exists():
                try:
                    dest_path.unlink()
                except Exception:
                    pass
            return False
