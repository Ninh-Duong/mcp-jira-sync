"""Encryption at rest for .ai-context/. The only module that touches the cipher. Contract: docs/AI_CONTEXT_FORMAT.md"""
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from core.config import JiraConfig
from core.jira_client import JiraClient
from utils.logger import get_logger

logger = get_logger("vault")

# Every file under .ai-context/ is a Fernet token named <original name> + ENC_SUFFIX
ENC_SUFFIX = ".enc"


class NoAccessError(Exception):
    """The gate refused: no key, no Jira login, or a file that does not decrypt. The message starts with 'No access:'."""


def unlock(config: JiraConfig) -> Fernet:
    """The access gate: the key must be set AND the Jira account must log in right now."""
    if not config.ai_context_key:
        raise NoAccessError("No access: JIRA_AI_CONTEXT_KEY is not set. Run `python cli.py` to log in, or inject it like JIRA_API_TOKEN.")
    try:
        fernet = Fernet(config.ai_context_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise NoAccessError("No access: JIRA_AI_CONTEXT_KEY is not a valid key (32 url-safe base64 bytes).")
    if not config.is_configured:
        raise NoAccessError("No access: the Jira account is not configured. Run `python cli.py` to log in.")
    # ponytail: one /myself request per call, add a short cache if reads get slow
    try:
        JiraClient(config).verify_account()
    except Exception as e:
        logger.warning(f"Access check failed: {type(e).__name__}")
        raise NoAccessError("No access: cannot log in to Jira with the configured account. Run `python cli.py` to log in.")
    return fernet


def write_encrypted(path: Path, data: bytes, fernet: Fernet) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(fernet.encrypt(data))


def read_encrypted(path: Path, fernet: Fernet) -> bytes:
    try:
        return fernet.decrypt(path.read_bytes())
    except InvalidToken:
        raise NoAccessError(f"No access: cannot decrypt {path.name} (wrong JIRA_AI_CONTEXT_KEY, or the file was modified).")
