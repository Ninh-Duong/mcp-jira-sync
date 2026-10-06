import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.adf_parser import adf_to_markdown
from core.config import JiraConfig, TICKETS_DIR, load_config
from core.indexer import register_ticket
from core.jira_client import JiraClient, JiraApiError
from utils.logger import get_logger

logger = get_logger("sync_service")

# Image mime types eligible for local download
IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
}


@dataclass
class SyncResult:
    success: bool
    key: str
    ticket_file: Optional[Path] = None
    history_file: Optional[Path] = None
    assets_downloaded: int = 0
    message: str = ""


def _sanitize_filename(name: str) -> str:
    """Sanitizes file names for cross-platform filesystem safety."""
    return re.sub(r'[\\/*?:"<>|]', "_", name)


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
    images: List[Dict[str, str]],
    other_files: List[Dict[str, Any]],
    relations: Dict[str, Any],
) -> str:
    """Renders primary ticket.md containing YAML frontmatter and structured sections."""
    # Build YAML frontmatter for machine reading
    frontmatter = [
        "---",
        f"key: {meta['key']}",
        f'summary: "{meta["summary"].replace('"', '\\"')}"',
        f"status: {meta['status']}",
        f"type: {meta['type']}",
        f"priority: {meta['priority']}",
        f"assignee: {meta['assignee']}",
        f"reporter: {meta['reporter']}",
        f"created: {meta['created']}",
        f"updated: {meta['updated']}",
        f"url: {meta['url']}",
        f"labels: {meta['labels']}",
        f"assets_count: {len(images)}",
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
        f"> **Changelog**: Detailed history available at [history.md](history.md)  ",
        "",
        "## 1. Description & Requirements",
        desc_md,
        "",
    ]

    # Visual assets
    body.append("## 2. Visual Assets & Screenshots")
    if images:
        for img in images:
            filename = img["filename"]
            rel_asset_path = f"assets/{filename}"
            body.append(f"### 📷 {filename}")
            body.append(f"![{filename}]({rel_asset_path})\n")
    else:
        body.append("*No image attachments found.*\n")

    # Other files
    if other_files:
        body.append("## 3. Other Attachments & Documents")
        for f in other_files:
            size_kb = round(f.get("size", 0) / 1024, 1)
            body.append(f"- [{f.get('filename')}]({f.get('content')}) ({size_kb} KB)")
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

    def sync(self, issue_key: str) -> SyncResult:
        """Executes full synchronization for a specific Jira issue."""
        # Extract ticket key even if user enters a full Jira URL (e.g. /browse/KEY-123)
        match = re.search(r"([A-Za-z0-9]+-[0-9]+)", issue_key)
        if not match:
            msg = f"Invalid ticket key: '{issue_key}'. Expected format: PROJECT-123 (e.g. PROJ-123)."
            logger.warning(msg)
            return SyncResult(success=False, key=issue_key.strip(), message=msg)
        key = match.group(1).upper()

        if not self.config.is_configured:
            msg = "Jira account not configured. Please set up credentials via CLI or .env file."
            logger.error(msg)
            return SyncResult(success=False, key=key, message=msg)

        logger.info(f"Starting sync workflow for {key}")

        try:
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
            ticket_dir = TICKETS_DIR / key
            assets_dir = ticket_dir / "assets"
            ticket_dir.mkdir(parents=True, exist_ok=True)

            # 4. Process Attachments (download images, record files)
            attachments = fields.get("attachment", [])
            downloaded_images: List[Dict[str, str]] = []
            other_files: List[Dict[str, Any]] = []

            for att in attachments:
                filename = _sanitize_filename(att.get("filename", "asset"))
                mime_type = att.get("mimeType", "").lower()
                content_url = att.get("content", "")

                if mime_type in IMAGE_MIME_TYPES:
                    dest_file = assets_dir / filename
                    ok = self.client.download_attachment(content_url, dest_file)
                    if ok:
                        downloaded_images.append({"filename": filename, "mime": mime_type})
                else:
                    other_files.append(att)

            # Purge obsolete assets no longer present in Jira attachments
            valid_asset_names = {
                _sanitize_filename(att.get("filename", "asset"))
                for att in attachments
                if att.get("mimeType", "").lower() in IMAGE_MIME_TYPES
            }
            if assets_dir.exists():
                for f in assets_dir.iterdir():
                    if f.is_file() and f.name not in valid_asset_names:
                        f.unlink()
                        logger.info(f"Removed obsolete asset: {f.name}")
                if not any(assets_dir.iterdir()):
                    assets_dir.rmdir()

            # 5. Convert description ADF -> Markdown
            raw_desc = fields.get("description")
            desc_md = adf_to_markdown(raw_desc)

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
                images=downloaded_images,
                other_files=other_files,
                relations=relations,
            )

            ticket_file = ticket_dir / "ticket.md"
            ticket_file.write_text(ticket_md_content, encoding="utf-8")
            logger.info(f"Wrote ticket markdown: {ticket_file}")

            # 7. Build and write history.md (changelog)
            changelog_data = issue_data.get("changelog", {})
            histories = changelog_data.get("histories", [])
            history_md_content = _format_history_markdown(key, summary, histories)

            history_file = ticket_dir / "history.md"
            history_file.write_text(history_md_content, encoding="utf-8")
            logger.info(f"Wrote history changelog: {history_file} ({len(histories)} entries)")

            # 8. Register in INDEX.md and catalog.json
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
                "ticket_path": f"tickets/{key}/ticket.md",
                "history_path": f"tickets/{key}/history.md",
                "labels": labels,
            }
            register_ticket(index_meta)

            success_msg = (
                f"Successfully synced ticket {key} to {ticket_file.relative_to(ticket_dir.parent.parent)} "
                f"with {len(downloaded_images)} image(s) and {len(histories)} changelog entries."
            )
            logger.info(success_msg)
            return SyncResult(
                success=True,
                key=key,
                ticket_file=ticket_file,
                history_file=history_file,
                assets_downloaded=len(downloaded_images),
                message=success_msg,
            )

        except JiraApiError as e:
            logger.error(f"Jira API error while syncing {key}: {e}", exc_info=True)
            return SyncResult(success=False, key=key, message=str(e))
        except Exception as e:
            logger.error(f"Unexpected error while syncing {key}: {e}", exc_info=True)
            return SyncResult(success=False, key=key, message=f"Unexpected error: {str(e)}")
