import sys
from pathlib import Path

# Force UTF-8 on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure root directory is in sys.path (100% relative path resolution)
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils.env_check import verify_environment

# Pre-flight check only when run as a script: importing this module (e.g. from a parent MCP) must never exit
if __name__ == "__main__":
    verify_environment(exit_on_error=True)

from utils.logger import setup_logging, get_logger
from core.config import load_config, AI_CONTEXT_DIR, INDEX_FILE
from core.jira_client import JiraClient
from core.sync_service import SyncService
from core.indexer import list_indexed_tickets

server_logger = get_logger("mcp_server")


def jira_instructions(prefix: str = "") -> str:
    """MCP server instructions: the only guidance an agent in another repository gets. Keep in sync with AGENTS.md."""
    return (
        "jira-sync-ticket: sync Jira Cloud tickets into local Markdown context for AI agents.\n"
        f"- Before working on a Jira ticket, call {prefix}jira_sync_ticket(issue_key) with a key (PROJ-123) or a /browse/ URL.\n"
        "- It returns ABSOLUTE paths. Read ticket.md first (YAML frontmatter + description + images in assets/), "
        "then history.md (changelog, newest first) to see how requirements changed.\n"
        f"- {prefix}jira_list_synced lists tickets already synced (no Jira call).\n"
        "- Files under .ai-context/ are generated: never edit them; re-sync instead.\n"
        f"- On an auth or permission error, call {prefix}jira_check_connection and tell the user to run `python cli.py` to log in. "
        "Never ask the user to paste a token into chat."
    )


def jira_sync_ticket(issue_key: str) -> str:
    """Synchronizes a Jira ticket (converts ADF description to Markdown, downloads image attachments, and extracts changelog history) into the local .ai-context/ directory for AI Agents.

    Args:
        issue_key: Jira issue key, e.g. 'PROJ-123', or a full Jira /browse/ URL.

    Returns:
        Absolute paths to the generated markdown files and a synchronization summary.
    """
    server_logger.info(f"MCP tool call: jira_sync_ticket('{issue_key}')")
    service = SyncService()
    result = service.sync(issue_key)

    if result.success:
        ticket_path = result.ticket_file.as_posix() if result.ticket_file else ""
        history_path = result.history_file.as_posix() if result.history_file else ""
        return (
            f"✅ Ticket {result.key} synchronized successfully!\n"
            f"- Ticket Details & Description : {ticket_path}\n"
            f"- Changelog & Evolution History : {history_path}\n"
            f"- Downloaded Images/Diagrams    : {result.assets_downloaded} image(s)\n"
            f"- Master Catalog Index          : {INDEX_FILE.as_posix()}\n\n"
            f"AI Agent: Please read '{ticket_path}' for core requirements and visual assets before starting work."
        )
    else:
        server_logger.error(f"Failed to sync {issue_key}: {result.message}")
        return f"❌ Error syncing ticket {issue_key}: {result.message}\n(See details in logs/app.log)"


def jira_list_synced() -> str:
    """Lists all Jira tickets that have already been synchronized into the local .ai-context/ catalog."""
    server_logger.info("MCP tool call: jira_list_synced()")
    tickets = list_indexed_tickets()
    if not tickets:
        return "No tickets have been synchronized yet in .ai-context/. Call 'jira_sync_ticket' first."

    lines = [f"Found {len(tickets)} synchronized ticket(s):"]
    for t in tickets:
        ticket_path = (AI_CONTEXT_DIR / t.get("ticket_path", "")).as_posix()
        lines.append(
            f"- [{t['key']}] {t.get('summary')} | Status: {t.get('status')} | Assignee: {t.get('assignee')} | File: {ticket_path}"
        )
    return "\n".join(lines)


def jira_check_connection() -> str:
    """Validates connectivity to Jira Cloud and checks current user profile."""
    server_logger.info("MCP tool call: jira_check_connection()")
    config = load_config()
    if not config.is_configured:
        return "Jira credentials are not configured yet. Please configure .env or run CLI to log in."

    client = JiraClient(config)
    try:
        user = client.verify_account()
        return (
            f"✅ Jira Cloud connection active!\n"
            f"- Base URL : {config.clean_base_url}\n"
            f"- User     : {user.get('displayName')} ({user.get('emailAddress')})"
        )
    except Exception as e:
        server_logger.error(f"Connection check error: {e}", exc_info=True)
        return f"❌ Jira connection error: {str(e)} (See details in logs/app.log)"


def register_jira_tools(app, prefix: str = "") -> None:
    """Mounts the Jira tools on any MCPServer / FastMCP instance (standalone or a parent MCP)."""
    from mcp.types import ToolAnnotations

    app.add_tool(
        jira_sync_ticket,
        name=f"{prefix}jira_sync_ticket",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True),
    )
    app.add_tool(
        jira_list_synced,
        name=f"{prefix}jira_list_synced",
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    app.add_tool(
        jira_check_connection,
        name=f"{prefix}jira_check_connection",
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    )


def create_server():
    """Builds the standalone server (mcp 2.x MCPServer, falling back to mcp 1.x FastMCP)."""
    try:
        from mcp.server import MCPServer
    except ImportError:
        from mcp.server.fastmcp import FastMCP as MCPServer
    app = MCPServer("jira-sync-ticket", instructions=jira_instructions())
    register_jira_tools(app)
    return app


def main() -> None:
    setup_logging()
    server_logger.info("Starting Jira Sync MCP Server over stdio...")
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
