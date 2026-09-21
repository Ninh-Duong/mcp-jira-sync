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
from utils.logger import setup_logging, get_logger

# Pre-flight environment check
verify_environment(exit_on_error=True)

# Logger will direct file logs to logs/app.log and console logs to stderr
logger = setup_logging()
server_logger = get_logger("mcp_server")

try:
    from mcp.server import MCPServer
    mcp_app = MCPServer("jira-sync-ticket")
except ImportError:
    from mcp.server.fastmcp import FastMCP
    mcp_app = FastMCP("jira-sync-ticket")

from core.config import load_config, INDEX_FILE
from core.jira_client import JiraClient
from core.sync_service import SyncService
from core.indexer import list_indexed_tickets


@mcp_app.tool()
def jira_sync_ticket(issue_key: str) -> str:
    """Synchronizes a Jira ticket (converts ADF description to Markdown, downloads image attachments, and extracts changelog history) into the local .ai-context/ directory for AI Agents.

    Args:
        issue_key: Jira issue key, e.g. 'PROJ-123' or 'ISSUE-456'.

    Returns:
        Path to generated markdown file and synchronization summary.
    """
    server_logger.info(f"MCP tool call: jira_sync_ticket('{issue_key}')")
    service = SyncService()
    result = service.sync(issue_key)

    if result.success:
        ticket_rel = result.ticket_file.relative_to(ROOT_DIR) if result.ticket_file else ""
        history_rel = result.history_file.relative_to(ROOT_DIR) if result.history_file else ""
        return (
            f"✅ Ticket {result.key} synchronized successfully!\n"
            f"- Ticket Details & Description : {ticket_rel}\n"
            f"- Changelog & Evolution History : {history_rel}\n"
            f"- Downloaded Images/Diagrams    : {result.assets_downloaded} image(s)\n"
            f"- Master Catalog Index          : {INDEX_FILE.relative_to(ROOT_DIR)}\n\n"
            f"AI Agent: Please read '{ticket_rel}' for core requirements and visual assets before starting work."
        )
    else:
        server_logger.error(f"Failed to sync {issue_key}: {result.message}")
        return f"❌ Error syncing ticket {issue_key}: {result.message}\n(See details in logs/app.log)"


@mcp_app.tool()
def jira_list_synced() -> str:
    """Lists all Jira tickets that have already been synchronized into the local .ai-context/ catalog."""
    server_logger.info("MCP tool call: jira_list_synced()")
    tickets = list_indexed_tickets()
    if not tickets:
        return "No tickets have been synchronized yet in .ai-context/. Call 'jira_sync_ticket' first."

    lines = [f"Found {len(tickets)} synchronized ticket(s):"]
    for t in tickets:
        lines.append(
            f"- [{t['key']}] {t.get('summary')} | Status: {t.get('status')} | Assignee: {t.get('assignee')} | File: {t.get('ticket_path')}"
        )
    return "\n".join(lines)


@mcp_app.tool()
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


def main() -> None:
    server_logger.info("Starting Jira Sync MCP Server over stdio...")
    mcp_app.run(transport="stdio")


if __name__ == "__main__":
    main()
