"""Encryption at rest for .ai-context/. The only module that touches the cipher. Contract: docs/AI_CONTEXT_FORMAT.md"""
import hashlib
import time
from pathlib import Path
from typing import Dict

from cryptography.fernet import Fernet, InvalidToken

from core.config import JiraConfig
from core.jira_client import JiraClient
from utils.logger import get_logger

logger = get_logger("vault")

# Every file under .ai-context/ is a Fernet token named <original name> + ENC_SUFFIX
ENC_SUFFIX = ".enc"

# A successful Jira login check is trusted this long per process and account (FEATURES.md F7 rule 3)
ACCESS_TTL_SECONDS = 60.0
_clock = time.monotonic  # tests patch this to control time
_access_ok: Dict[str, float] = {}  # account fingerprint -> _clock() of the last successful check


def _account_fingerprint(config: JiraConfig) -> str:
    """SHA-256 of site, email and token: the token itself is never stored or logged."""
    raw = "\n".join((config.clean_base_url, config.email, config.api_token)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class NoAccessError(Exception):
    """The gate refused: no key, no Jira login, or a file that does not decrypt. The message starts with 'No access:'."""


def unlock(config: JiraConfig) -> Fernet:
    """The access gate: the key must be set AND the Jira account must log in (checked at most once per ACCESS_TTL_SECONDS)."""
    if not config.ai_context_key:
        raise NoAccessError("No access: JIRA_AI_CONTEXT_KEY is not set. Run `python cli.py` to log in, or inject it like JIRA_API_TOKEN.")
    try:
        fernet = Fernet(config.ai_context_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise NoAccessError("No access: JIRA_AI_CONTEXT_KEY is not a valid key (32 url-safe base64 bytes).")
    if not config.is_configured:
        raise NoAccessError("No access: the Jira account is not configured. Run `python cli.py` to log in.")
    account = _account_fingerprint(config)
    checked_at = _access_ok.get(account)
    if checked_at is not None and _clock() - checked_at < ACCESS_TTL_SECONDS:
        return fernet
    try:
        JiraClient(config).verify_account()
    except Exception as e:
        _access_ok.pop(account, None)  # failures are never cached
        logger.warning(f"Access check failed: {type(e).__name__}")
        raise NoAccessError("No access: cannot log in to Jira with the configured account. Run `python cli.py` to log in.")
    _access_ok[account] = _clock()
    return fernet


def write_encrypted(path: Path, data: bytes, fernet: Fernet) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(fernet.encrypt(data))


def read_encrypted(path: Path, fernet: Fernet) -> bytes:
    try:
        return fernet.decrypt(path.read_bytes())
    except InvalidToken:
        raise NoAccessError(f"No access: cannot decrypt {path.name} (wrong JIRA_AI_CONTEXT_KEY, or the file was modified).")
