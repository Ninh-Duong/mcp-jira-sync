import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import CATALOG_FILE, INDEX_FILE, TICKETS_DIR
from utils.logger import get_logger

logger = get_logger("indexer")


def _read_catalog() -> Dict[str, Any]:
    """Loads existing catalog.json or returns default template."""
    if CATALOG_FILE.exists():
        try:
            return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Error reading catalog.json, recreating fresh index: {e}", exc_info=True)
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_tickets": 0,
        "tickets": {},
    }


def _write_catalog(catalog: Dict[str, Any]) -> None:
    """Saves updated catalog.json."""
    CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_FILE.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")


def _generate_index_markdown(catalog: Dict[str, Any]) -> None:
    """Renders human- and AI-readable INDEX.md from catalog data."""
    tickets = list(catalog.get("tickets", {}).values())
    # Sort by updated_at descending
    tickets.sort(key=lambda x: x.get("jira_updated_at", ""), reverse=True)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "# 📋 Synced Jira Tickets Catalog (.ai-context)",
        "",
        f"> **Last updated**: {now_str} | **Total tickets**: {len(tickets)}",
        "",
        "This catalog is automatically generated for **AI Agents** to discover and understand project tickets at a glance.",
        "",
        "| Ticket Key | Type | Status | Priority | Assignee | Summary | Detailed Context |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for t in tickets:
        key = t.get("key", "")
        t_type = t.get("type", "Issue")
        status = t.get("status", "N/A")
        priority = t.get("priority", "N/A")
        assignee = t.get("assignee", "Unassigned")
        summary = t.get("summary", "").replace("|", "-")
        # Relative link from INDEX.md
        rel_path = f"tickets/{key}/ticket.md"
        lines.append(
            f"| **{key}** | {t_type} | `{status}` | {priority} | {assignee} | {summary} | [{key}/ticket.md]({rel_path}) |"
        )

    lines.append("")
    lines.append("## AI Agent Guidelines:")
    lines.append("1. Locate your target ticket key in the table above.")
    lines.append("2. Read `tickets/<KEY>/ticket.md` for full requirements, description, and visual diagram links.")
    lines.append("3. Read `tickets/<KEY>/history.md` to understand chronological requirement evolution and status transitions.")
    lines.append("")

    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text("\n".join(lines), encoding="utf-8")
    logger.debug(f"Regenerated {INDEX_FILE} with {len(tickets)} tickets")


def register_ticket(meta: Dict[str, Any]) -> None:
    """Updates index with newly synced ticket metadata and regenerates INDEX.md."""
    key = meta.get("key", "").upper()
    if not key:
        return

    catalog = _read_catalog()
    catalog["tickets"][key] = meta
    catalog["total_tickets"] = len(catalog["tickets"])
    catalog["updated_at"] = datetime.now(timezone.utc).isoformat()

    _write_catalog(catalog)
    _generate_index_markdown(catalog)
    logger.info(f"Registered ticket {key} into catalog and updated INDEX.md")


def list_indexed_tickets() -> List[Dict[str, Any]]:
    """Returns list of all synced ticket metadata."""
    catalog = _read_catalog()
    tickets = list(catalog.get("tickets", {}).values())
    tickets.sort(key=lambda x: x.get("jira_updated_at", ""), reverse=True)
    return tickets


def get_indexed_ticket(issue_key: str) -> Optional[Dict[str, Any]]:
    """Returns metadata for a specific synced ticket if exists."""
    catalog = _read_catalog()
    return catalog.get("tickets", {}).get(issue_key.strip().upper())
