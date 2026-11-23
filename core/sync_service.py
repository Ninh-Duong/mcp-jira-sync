import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.adf_parser import adf_to_markdown
from core.attachments import ATTACHMENT_SCHEMA, IMAGE_MIME_TYPES, cache_complete, link_attachments, sync_attachments
from core.config import JiraConfig, TICKETS_DIR, load_config
from core.indexer import get_indexed_ticket, register_ticket
from core.jira_client import JiraClient, JiraApiError
from core.vault import ENC_SUFFIX, NoAccessError, read_encrypted, unlock, write_encrypted
from utils.logger import get_logger

logger = get_logger("sync_service")

# ticket.md frontmatter keys, in order. Contract: docs/AI_CONTEXT_FORMAT.md
FRONTMATTER_KEYS = (
    "key", "summary", "status", "type", "priority", "assignee", "reporter",
    "created", "updated", "url", "labels", "assets_count",
)


@dataclass
class SyncResult:
    success: bool
    key: str
    ticket_file: Optional[Path] = None
    history_file: Optional[Path] = None
    assets_downloaded: int = 0  # images in the cache after this sync (downloaded now or reused)
    message: str = ""
    unchanged: bool = False  # Jira `updated` matched the cache: nothing was fetched or written (F9)
    assets_reused: int = 0  # images kept from the cache because id and size matched (F9)
    attachments_count: int = 0
    attachments_cached: int = 0
    attachments_reused: int = 0
    attachments_unavailable: int = 0


# Jira project keys start with a letter and may contain letters, digits and underscores
_KEY = r"[A-Za-z][A-Za-z0-9_]*-[0-9]+"


def extract_issue_key(text: str) -> Optional[str]:
    """Returns the upper-cased issue key from a bare key or a Jira URL (/browse/KEY or ?selectedIssue=KEY), else None.

    Only those URL positions are searched, so a hostname like team-2.atlassian.net is never taken for a key.
    """
    text = text.strip()
    match = re.fullmatch(_KEY, text) or re.search(rf"(?:/browse/|selectedIssue=)({_KEY})", text)
    if not match:
        return None
    return (match.group(1) if match.groups() else match.group(0)).upper()


def read_synced_file(issue_key: str, name: str, fernet) -> bytes:
    """Decrypts tickets/<KEY>/<name>.enc, where name is 'ticket.md', 'history.md' or 'assets/<file>'.

    Raises ValueError for a bad key or a name that leaves the ticket folder, FileNotFoundError when not synced,
    NoAccessError when the file does not decrypt.
    """
    key = extract_issue_key(issue_key)
    if not key:
        raise ValueError(f"Invalid ticket key: '{issue_key}'. Expected PROJECT-123 or a Jira /browse/PROJECT-123 URL.")
    ticket_dir = (TICKETS_DIR / key).resolve()
    path = (ticket_dir / f"{name}{ENC_SUFFIX}").resolve()
    if ticket_dir not in path.parents:
        raise ValueError(f"Invalid file name: '{name}'.")
    if not path.is_file():
        raise FileNotFoundError(f"{key} has no synced '{name}'. Call jira_sync_ticket first.")
    return read_encrypted(path, fernet)


def read_attachment(issue_key: str, filename: str, fernet):
    """Read a listed cached attachment; legacy caches permit image reads only."""
    import mimetypes

    key = extract_issue_key(issue_key)
    name = filename.strip().removeprefix("assets/")
    if not key or not name or any(c in name for c in ("/", "\\")) or name in {".", ".."}:
        raise ValueError("Invalid attachment reference; use a filename listed by this ticket.")
    cached = get_indexed_ticket(key, fernet) or {}
    records = cached.get("attachments")
    if records is not None:
        record = next((r for r in records if r["filename"] == name), None)
        if record is None or record.get("status") != "cached":
            raise ValueError("Attachment is not cached; sync the ticket and inspect its attachment status.")
        mime = record["mime"]
        original = record["original_filename"]
    else:
        mime = mimetypes.guess_type(name)[0]
        if mime not in IMAGE_MIME_TYPES:
            raise ValueError("Legacy cache supports images only; sync to include all attachments.")
        original = name
    return read_synced_file(key, "assets/" + name, fernet), mime, original


def _attachment_details(record: Dict[str, Any]) -> str:
    original = json.dumps(record.get("original_filename", record["filename"]), ensure_ascii=False)
    return (f"Original filename: {original}; MIME: {record.get('mime', 'application/octet-stream')}; "
            f"size: {record.get('size', 'unknown')} bytes; status: {record.get('status', 'cached')}.")


def _format_history_markdown(key: str, summary: str, histories: List[Dict[str, Any]]) -> str:
    """Renders chronological changelog into clean Markdown."""
    lines = [
        f"# 📜 Change History (Changelog): [{key}] {summary}",
        "",
        "> Chronological order: Newest to oldest. Helps AI Agents understand requirement evolution and status transitions.",
        "",
    ]

    if not histories:
        lines.append("*No changelog entries recorded.*")
        return "\n".join(lines)

    # Sort histories descending (newest first)
    sorted_histories = sorted(histories, key=lambda h: h.get("created", ""), reverse=True)

    for h in sorted_histories:
        author = h.get("author", {}).get("displayName", "System / Anonymous")
        created = h.get("created", "N/A")
        items = h.get("items", [])

        lines.append(f"### ⏱️ {created} — Updated by: **{author}**")
        for item in items:
            field = item.get("field", "field")
            from_val = item.get("fromString") or "(empty)"
            to_val = item.get("toString") or "(empty)"

            if field.lower() in ("description", "mô tả"):
                lines.append(f"- **{field}**: Description updated.")
            else:
                lines.append(f"- **{field}**: `{from_val}` ➔ `{to_val}`")
        lines.append("")

    return "\n".join(lines)


def _format_ticket_markdown(
    meta: Dict[str, Any],
    desc_md: str,
    images: List[Dict[str, Any]],
    other_files: List[Dict[str, Any]],
    relations: Dict[str, Any],
) -> str:
    """Renders primary ticket.md containing YAML frontmatter and structured sections."""
    # Build YAML frontmatter for machine reading
    frontmatter = [
        "---",
        # JSON scalars are valid YAML (double-quoted strings, flow lists), so every value parses safely
        *(f"{k}: {json.dumps(meta[k], ensure_ascii=False)}" for k in FRONTMATTER_KEYS[:-1]),
        f"assets_count: {sum(img.get('status', 'cached') == 'cached' for img in images)}",
        "---",
        "",
    ]

    # Content body
    body = [
        f"# [{meta['key']}] {meta['summary']}",
        "",
        f"> **Source**: [Jira Cloud]({meta['url']})  ",
        f"> **Type**: `{meta['type']}` | **Status**: `{meta['status']}` | **Priority**: `{meta['priority']}`  ",
        f"> **Assignee**: {meta['assignee']} | **Reporter**: {meta['reporter']}  ",
        f"> **Last Updated**: {meta['updated']}  ",
        "> **Changelog**: Detailed history available at [history.md](history.md)  ",
        "",
        "## 1. Description & Requirements",
        desc_md,
        "",
    ]

    total = len(images) + len(other_files)
    cached = sum(item.get("status", "cached") == "cached" for item in images + other_files)
    body.append(f"Attachments: {total} total; {cached} cached; {total - cached} unavailable.\n")
    # Visual assets
    body.append("## 2. Visual Assets & Screenshots")
    if images:
        for img in images:
            filename = img["filename"]
            rel_asset_path = f"assets/{filename}"
            body.append(f"### 📷 {filename}")
            body.append(_attachment_details(img))
            if img.get("status", "cached") == "cached":
                body.append(f"![{filename}]({rel_asset_path})\n")
    else:
        body.append("*No image attachments found.*\n")

    # Other files
    if other_files:
        body.append("## 3. Other Attachments & Documents")
        for f in other_files:
            body.append("- " + _attachment_details(f))
            if f.get("status", "cached") == "cached":
                body.append(f"  [{f['filename']}](assets/{f['filename']})")
        body.append("")

    # Relationships
    body.append("## 4. Related Issues & Dependencies")
    parent = relations.get("parent")
    if parent:
        body.append(f"- **Parent Issue**: [{parent.get('key')}] {parent.get('fields', {}).get('summary', '')}")

    subtasks = relations.get("subtasks", [])
    if subtasks:
        body.append("- **Subtasks**:")
        for st in subtasks:
            body.append(
                f"  - [{st.get('key')}] `{st.get('fields', {}).get('status', {}).get('name')}` - {st.get('fields', {}).get('summary')}"
            )

    links = relations.get("links", [])
    if links:
        body.append("- **Issue Links**:")
        for link in links:
            l_type = link.get("type", {}).get("name", "Relates")
            inward = link.get("inwardIssue")
            outward = link.get("outwardIssue")
            if inward:
                body.append(f"  - *{link.get('type', {}).get('inward', l_type)}*: [{inward.get('key')}] {inward.get('fields', {}).get('summary')}")
            if outward:
                body.append(f"  - *{link.get('type', {}).get('outward', l_type)}*: [{outward.get('key')}] {outward.get('fields', {}).get('summary')}")

    if not parent and not subtasks and not links:
        body.append("*No related dependencies recorded.*")

    body.append("")
    return "\n".join(frontmatter + body)


class SyncService:
    """Service handling ticket retrieval, asset persistence, and index updates."""

    def __init__(self, config: Optional[JiraConfig] = None):
        self.config = config or load_config()
        self.client = JiraClient(self.config)

    def _unchanged_result(
        self, key: str, cached: Dict[str, Any], ticket_file: Path, history_file: Path
    ) -> Optional[SyncResult]:
        """The cached result when the ticket is cached and Jira's `updated` (light `fields=updated` request) still matches."""
        cached_updated = cached.get("jira_updated_at")
        if not (cached_updated and ticket_file.is_file() and history_file.is_file()
                and cache_complete(cached, ticket_file.parent / "assets")):
            return None
        if self.client.get_issue_updated(key) != cached_updated:
            return None
        msg = f"Ticket {key} is up to date (unchanged in Jira since the last sync); nothing was downloaded."
        logger.info(msg)
        return SyncResult(
            success=True,
            key=key,
            ticket_file=ticket_file,
            history_file=history_file,
            assets_downloaded=cached.get("assets_count", 0),
            message=msg,
            unchanged=True,
            attachments_count=cached.get("attachments_count", 0),
            attachments_cached=cached.get("attachments_count", 0),
        )

    def sync(self, issue_key: str, force: bool = False) -> SyncResult:
        """Syncs one Jira issue. Unless `force`, a cached ticket whose Jira `updated` is unchanged is left as is (F9)."""
        key = extract_issue_key(issue_key)
        if not key:
            msg = f"Invalid ticket key: '{issue_key}'. Expected PROJECT-123 or a Jira /browse/PROJECT-123 URL."
            logger.warning(msg)
            return SyncResult(success=False, key=issue_key.strip(), message=msg)

        if not self.config.is_configured:
            msg = "Jira account not configured. Set the hub's `jira` block (CENTRAL_CONFIG_PATH) or .env via `python cli.py`."
            logger.error(msg)
            return SyncResult(success=False, key=key, message=msg)

        logger.info(f"Starting sync workflow for {key}")

        try:
            # 0. Access gate: nothing is written unless the key is set and the Jira login works
            fernet = unlock(self.config)

            ticket_dir = TICKETS_DIR / key
            ticket_file = ticket_dir / f"ticket.md{ENC_SUFFIX}"
            history_file = ticket_dir / f"history.md{ENC_SUFFIX}"
            cached = get_indexed_ticket(key, fernet) or {}

            # 0b. Up-to-date check: one light request for `updated` instead of the full fetch and every download
            if not force:
                unchanged = self._unchanged_result(key, cached, ticket_file, history_file)
                if unchanged:
                    return unchanged

            # 1. Fetch issue payload
            issue_data = self.client.get_issue(key)
            fields = issue_data.get("fields", {})

            # 2. Extract metadata
            summary = fields.get("summary", "No Summary Provided")
            status_obj = fields.get("status") or {}
            status_name = status_obj.get("name", "N/A")
            type_name = (fields.get("issuetype") or {}).get("name", "Issue")
            priority_name = (fields.get("priority") or {}).get("name", "N/A")
            assignee_name = (fields.get("assignee") or {}).get("displayName", "Unassigned")
            reporter_name = (fields.get("reporter") or {}).get("displayName", "Unknown")
            created_at = fields.get("created", "")
            updated_at = fields.get("updated", "")
            labels = fields.get("labels", [])
            jira_url = f"{self.config.clean_base_url}/browse/{key}"

            # 3. Destination folders (100% relative resolution)
            assets_dir = ticket_dir / "assets"
            ticket_dir.mkdir(parents=True, exist_ok=True)

            # 4. Cache every attachment type; failures remain visible in the manifest.
            records = sync_attachments(self.client, fields.get("attachment") or [], assets_dir, cached.get("assets", {}), fernet)
            images = [r for r in records if r["mime"] in IMAGE_MIME_TYPES]
            downloaded_images = [r for r in images if r["status"] == "cached"]
            other_files = [r for r in records if r["mime"] not in IMAGE_MIME_TYPES]
            available = [r for r in records if r["status"] == "cached"]
            asset_identities = {r["filename"]: {"id": r["id"], "size": r["size"]} for r in available}
            reused = sum(bool(r.get("reused")) for r in downloaded_images)

            # 5. Convert description ADF -> Markdown
            raw_desc = fields.get("description")
            desc_md = link_attachments(adf_to_markdown(raw_desc), records)

            # 6. Build and write ticket.md
            meta_dict = {
                "key": key,
                "summary": summary,
                "status": status_name,
                "type": type_name,
                "priority": priority_name,
                "assignee": assignee_name,
                "reporter": reporter_name,
                "created": created_at,
                "updated": updated_at,
                "url": jira_url,
                "labels": labels,
            }

            relations = {
                "parent": fields.get("parent"),
                "subtasks": fields.get("subtasks", []),
                "links": fields.get("issuelinks", []),
            }

            ticket_md_content = _format_ticket_markdown(
                meta=meta_dict,
                desc_md=desc_md,
                images=images,
                other_files=other_files,
                relations=relations,
            )

            write_encrypted(ticket_file, ticket_md_content.encode("utf-8"), fernet)
            logger.info(f"Wrote ticket markdown: {ticket_file}")

            # 7. Build and write history.md (changelog)
            changelog_data = issue_data.get("changelog", {})
            histories = changelog_data.get("histories", [])
            history_md_content = _format_history_markdown(key, summary, histories)

            write_encrypted(history_file, history_md_content.encode("utf-8"), fernet)
            logger.info(f"Wrote history changelog: {history_file} ({len(histories)} entries)")

            # Plaintext copies written before encryption existed
            for legacy in ("ticket.md", "history.md"):
                (ticket_dir / legacy).unlink(missing_ok=True)

            # 8. Register in the encrypted catalog
            index_meta = {
                "key": key,
                "summary": summary,
                "type": type_name,
                "status": status_name,
                "priority": priority_name,
                "assignee": assignee_name,
                "jira_updated_at": updated_at,
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "assets_count": len(downloaded_images),
                "history_count": len(histories),
                "ticket_path": f"tickets/{key}/ticket.md{ENC_SUFFIX}",
                "history_path": f"tickets/{key}/history.md{ENC_SUFFIX}",
                "labels": labels,
                "assets": asset_identities,
                "attachment_schema": ATTACHMENT_SCHEMA,
                "attachments": records,
                "attachments_count": len(records),
                "attachments_complete": len(available) == len(records),
            }
            register_ticket(index_meta, fernet)

            success_msg = (
                f"Successfully synced ticket {key} to {ticket_file.relative_to(ticket_dir.parent.parent)} "
                f"with {len(downloaded_images)} image(s) ({reused} unchanged, not downloaded again) "
                f"and {len(available)}/{len(records)} attachments cached "
                f"and {len(histories)} changelog entries."
            )
            logger.info(success_msg)
            return SyncResult(
                success=True,
                key=key,
                ticket_file=ticket_file,
                history_file=history_file,
                assets_downloaded=len(downloaded_images),
                message=success_msg,
                assets_reused=reused,
                attachments_count=len(records),
                attachments_cached=len(available),
                attachments_reused=sum(bool(r.get("reused")) for r in available),
                attachments_unavailable=len(records) - len(available),
            )

        except (JiraApiError, NoAccessError) as e:
            logger.error(f"Jira API error while syncing {key}: {e}", exc_info=True)
            return SyncResult(success=False, key=key, message=str(e))
        except Exception as e:
            logger.error(f"Unexpected error while syncing {key}: {e}", exc_info=True)
            return SyncResult(success=False, key=key, message=f"Unexpected error: {str(e)}")
