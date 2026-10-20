import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any
from dotenv import dotenv_values, set_key

from utils.logger import get_logger

logger = get_logger("config")

# Project root determined dynamically (100% relative path resolution)
BASE_DIR = Path(__file__).resolve().parent.parent

ENV_FILE = BASE_DIR / ".env"


def _local_env() -> Dict[str, Optional[str]]:
    """Reads .env as a dict without touching os.environ, so injected variables and the central file keep priority."""
    # mcp-hub sets PYTHON_DOTENV_DISABLED=1; dotenv_values ignores that flag (only load_dotenv honours it), so check it here
    if os.getenv("PYTHON_DOTENV_DISABLED", "").casefold() in {"1", "true", "t", "yes", "y"}:
        return {}
    return dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}


# Standardized paths; AI_CONTEXT_DIR can be moved (env or .env), e.g. into the agent's workspace
LOGS_DIR = BASE_DIR / "logs"
AI_CONTEXT_DIR = Path(
    os.getenv("AI_CONTEXT_DIR") or _local_env().get("AI_CONTEXT_DIR") or BASE_DIR / ".ai-context"
).expanduser().resolve()
TICKETS_DIR = AI_CONTEXT_DIR / "tickets"
CATALOG_FILE = AI_CONTEXT_DIR / "catalog.json.enc"

# Project Permission Scheme Keys (Internal Jira Permissions)
REQUIRED_PERMISSIONS: List[Dict[str, str]] = [
    {
        "key": "BROWSE_PROJECTS",
        "name": "Browse Projects",
        "desc": "Ability to browse projects, search issues, and view ticket details.",
    },
]

# Atlassian REST API v3 Granular Scopes (OAuth 2.0 / App Scopes standard)
JIRA_GRANULAR_SCOPES: List[Dict[str, str]] = [
    {"scope": "read:me", "desc": "Access user profile and verify authentication (GET /rest/api/3/myself)"},
    {"scope": "read:jira-work", "desc": "Read Jira project and issue metadata (classic scope covering all issue reads)"},
    {"scope": "read:issue-details:jira", "desc": "Read ticket description, summary, fields, and links"},
    {"scope": "read:attachment:jira", "desc": "View and download attached screenshots and image assets"},
    {"scope": "read:issue.changelog:jira", "desc": "Read ticket requirement change history (NOT read:audit-log:jira)"},
]


@dataclass
class JiraConfig:
    base_url: str
    email: str
    api_token: str
    max_asset_size_mb: int = 15
    ai_context_key: str = ""  # Fernet key for .ai-context/ (core/vault.py); a secret like api_token

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.email and self.api_token)

    @property
    def clean_base_url(self) -> str:
        return self.base_url.rstrip("/") if self.base_url else ""


def load_config() -> JiraConfig:
    """Loads Jira configuration with priority:
    1. Process Environment Variables (injected dynamically by Master MCP)
    2. Central JSON Secrets file (via CENTRAL_CONFIG_PATH)
    3. Local .env file (standalone CLI fallback)
    """
    local = _local_env()

    # Support central tokens file if configured by Master MCP
    central_path_str = os.getenv("CENTRAL_CONFIG_PATH") or local.get("CENTRAL_CONFIG_PATH") or ""
    central_jira: Dict[str, Any] = {}
    if central_path_str:
        central_path = Path(central_path_str).expanduser().resolve()
        if central_path.exists():
            try:
                parsed = json.loads(central_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    central_jira = parsed.get("jira", parsed)
                logger.debug(f"Loaded central tokens from {central_path}")
            except Exception as e:
                logger.warning(f"Could not parse central config at {central_path}: {e}")

    def pick(env_key: str, central_key: str) -> str:
        return str(os.getenv(env_key) or central_jira.get(central_key) or local.get(env_key) or "").strip()

    base_url = pick("JIRA_BASE_URL", "base_url")
    email = pick("JIRA_EMAIL", "email")
    api_token = pick("JIRA_API_TOKEN", "api_token")

    try:
        max_size = int(pick("MAX_ASSET_SIZE_MB", "max_asset_size_mb") or 15)
    except ValueError:
        max_size = 15

    return JiraConfig(
        base_url=base_url,
        email=email,
        api_token=api_token,
        max_asset_size_mb=max_size,
        ai_context_key=pick("JIRA_AI_CONTEXT_KEY", "ai_context_key"),
    )


def save_config(base_url: str, email: str, api_token: str, max_asset_size_mb: int = 15) -> None:
    """Persists credentials into local .env, keeping any other lines (AI_CONTEXT_DIR, CENTRAL_CONFIG_PATH, comments).

    Adds a new JIRA_AI_CONTEXT_KEY only when no source (env, central JSON, .env) has one, so an existing key is never replaced.
    """
    values = {
        "JIRA_BASE_URL": base_url.strip().rstrip("/"),
        "JIRA_EMAIL": email.strip(),
        "JIRA_API_TOKEN": api_token.strip(),
        "MAX_ASSET_SIZE_MB": str(max_asset_size_mb),
    }
    if not load_config().ai_context_key:
        # Same bytes as Fernet.generate_key(); kept here so config.py stays free of the cipher
        values["JIRA_AI_CONTEXT_KEY"] = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")

    try:
        ENV_FILE.touch(exist_ok=True)
        for key, value in values.items():
            set_key(ENV_FILE, key, value, quote_mode="never")
        logger.info(f"Configuration saved successfully to {ENV_FILE}")
    except Exception as e:
        logger.error(f"Failed to write configuration to {ENV_FILE}: {e}", exc_info=True)
        raise
