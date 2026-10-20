import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from cryptography.fernet import Fernet

from core.config import CATALOG_FILE
from core.vault import read_encrypted, write_encrypted
from utils.logger import get_logger

logger = get_logger("indexer")


def _read_catalog(fernet: Fernet) -> Dict[str, Any]:
    """Loads and decrypts catalog.json.enc, or returns the empty template. A wrong key raises NoAccessError."""
    if CATALOG_FILE.exists():
        try:
            return json.loads(read_encrypted(CATALOG_FILE, fernet))
        except json.JSONDecodeError as e:
            logger.warning(f"Error reading {CATALOG_FILE.name}, recreating fresh index: {e}")
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_tickets": 0,
        "tickets": {},
    }


def register_ticket(meta: Dict[str, Any], fernet: Fernet) -> None:
    """Upserts the synced ticket's metadata into the encrypted catalog."""
    key = meta.get("key", "").upper()
    if not key:
        return

    catalog = _read_catalog(fernet)
    catalog["tickets"][key] = meta
    catalog["total_tickets"] = len(catalog["tickets"])
    catalog["updated_at"] = datetime.now(timezone.utc).isoformat()

    write_encrypted(CATALOG_FILE, json.dumps(catalog, indent=2, ensure_ascii=False).encode("utf-8"), fernet)
    # Plaintext index files written before encryption existed
    for legacy in ("catalog.json", "INDEX.md"):
        (CATALOG_FILE.parent / legacy).unlink(missing_ok=True)
    logger.info(f"Registered ticket {key} into the catalog")


def list_indexed_tickets(fernet: Fernet) -> List[Dict[str, Any]]:
    """Returns list of all synced ticket metadata, newest Jira update first."""
    tickets = list(_read_catalog(fernet).get("tickets", {}).values())
    tickets.sort(key=lambda x: x.get("jira_updated_at", ""), reverse=True)
    return tickets
