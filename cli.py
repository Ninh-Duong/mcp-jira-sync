import sys
from pathlib import Path

# Force UTF-8 on Windows console to prevent charmap encoding errors
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

# Pre-flight environment check before execution
verify_environment(exit_on_error=True)

logger = setup_logging()
cli_logger = get_logger("cli")

from core.config import (
    load_config,
    save_config,
    REQUIRED_PERMISSIONS,
    JIRA_GRANULAR_SCOPES,
    INDEX_FILE,
    CATALOG_FILE,
    TICKETS_DIR,
)
from core.jira_client import JiraClient, JiraApiError
from core.sync_service import SyncService
from core.indexer import list_indexed_tickets

# Global session tracking authenticated user & verified permissions
SESSION = {
    "user": None,
    "permissions": {},
}


def print_banner() -> None:
    print("\n" + "=" * 75)
    print("      🚀 JIRA TICKET SYNC FOR AI AGENTS (CLI & LOCAL MCP)")
    print("=" * 75)


def show_required_permissions_notice() -> None:
    """Displays the list of permissions and scope codes required before authenticating."""
    print("\n" + "=" * 75)
    print(" 🔐 ATLASSIAN JIRA PERMISSIONS & SCOPE CODES (LATEST STANDARD)")
    print("=" * 75)
    print(" 1. Personal API Token (Basic Auth - Inherits User Account Permissions):")
    print("    Your Atlassian account must have the following Project Permission:")
    for p in REQUIRED_PERMISSIONS:
        print(f"    • Key Code: {p['key']} ({p['name']})")
        print(f"      Description: {p['desc']}")
    print()
    print(" 2. OAuth 2.0 / Atlassian App Scopes (Granular Scopes - Latest Atlassian Standard):")
    print("    If using OAuth 2.0 or App Token, ensure the following Granular Scopes are granted:")
    for s in JIRA_GRANULAR_SCOPES:
        print(f"    • Scope: {s['scope']:<27} - {s['desc']}")
    print("-" * 75)
    print(" 📌 Generate Personal API Token at:")
    print("    https://id.atlassian.com/manage-profile/security/api-tokens")
    print("=" * 75 + "\n")


def print_account_permissions_summary(user_info: dict, permissions: dict) -> None:
    """Prints a clear summary of the account profile and verified permissions."""
    print("\n" + "=" * 75)
    print(" 👤 ACCOUNT STATUS & VERIFIED PERMISSIONS AUDIT")
    print("=" * 75)
    name = user_info.get("displayName", "Unknown")
    email = user_info.get("emailAddress", "N/A")
    account_id = user_info.get("accountId", "N/A")
    active = "Active (Verified)" if user_info.get("active", True) else "Inactive"

    print(f" • Account Name : {name}")
    print(f" • Email Address: {email}")
    print(f" • Status       : {active} [ID: {account_id[:16]}...]")
    print("\n 📋 Verified Permissions Check:")
    for p in REQUIRED_PERMISSIONS:
        key = p["key"]
        has_perm = permissions.get(key, False)
        icon = "✔" if has_perm else "✖"
        tag = "Granted (Ready)" if has_perm else "Missing Global Access"
        print(f"   [{icon}] {key:<20} : {tag} - {p['desc']}")

    print("\n 🌐 Granular Scope Equivalents (for reference):")
    for s in JIRA_GRANULAR_SCOPES:
        print(f"   • {s['scope']:<27} : {s['desc']}")
    print("=" * 75 + "\n")


def check_feature_permission(feature_name: str, required_perm: str = "BROWSE_PROJECTS") -> bool:
    """Checks if the account has required permission for a feature, warning if missing."""
    perms = SESSION.get("permissions", {})
    has_perm = perms.get(required_perm, False)

    if not has_perm:
        warn_msg = (
            f"⚠️ [PERMISSION WARNING]: Feature '{feature_name}' requires '{required_perm}'\n"
            f"   (or OAuth scopes: read:jira-work, read:issue-details:jira, read:attachment:jira).\n"
            f"   Your account did not pass the global '{required_perm}' check.\n"
            f"   If your target ticket is in a restricted project, Jira API may return HTTP 403 Forbidden."
        )
        print("\n" + "!" * 75)
        print(warn_msg)
        print("!" * 75 + "\n")
        cli_logger.warning(f"Feature '{feature_name}' invoked without verified '{required_perm}' permission")

        proceed = input("Do you still want to attempt this action? (y/n) [y]: ").strip().lower()
        if proceed in ("n", "no"):
            print("[*] Action cancelled by user.\n")
            return False

    return True


def prompt_login() -> bool:
    """Guides user through interactive credential input and verifies permissions."""
    show_required_permissions_notice()

    current = load_config()
    default_url = current.base_url or "https://your-domain.atlassian.net"

    url_input = input(f"Enter Jira Base URL [{default_url}]: ").strip()
    base_url = url_input if url_input else default_url

    email_prompt = f" [{current.email}]" if current.email else ""
    email_input = input(f"Enter Atlassian Email{email_prompt}: ").strip()
    email = email_input if email_input else current.email

    if not email:
        print("[!] Email cannot be empty.")
        return False

    token_prompt = " (press Enter to keep existing token)" if current.api_token else ""
    api_token = input(f"Enter Jira API Token{token_prompt}: ").strip().strip("'\"")
    if not api_token:
        api_token = current.api_token

    if not api_token:
        print("[!] API Token cannot be empty.")
        return False

    print("\n⏳ Verifying credentials with Jira Cloud...")
    from core.config import JiraConfig
    temp_config = JiraConfig(base_url=base_url, email=email, api_token=api_token)
    client = JiraClient(temp_config)

    try:
        user_info = client.verify_account()
        print(f"✅ Login successful: {user_info.get('displayName')} ({user_info.get('emailAddress')})")
    except JiraApiError as e:
        print(f"❌ Authentication failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return False

    # Check permissions
    print("⏳ Verifying account permissions...")
    perm_results = client.check_permissions(["BROWSE_PROJECTS"])

    # Update session
    SESSION["user"] = user_info
    SESSION["permissions"] = perm_results

    # Display audit summary
    print_account_permissions_summary(user_info, perm_results)

    # Save to .env
    save_config(base_url=base_url, email=email, api_token=api_token)
    print("💾 Configuration saved to .env successfully.\n")
    return True


def handle_sync_ticket() -> None:
    """Handles ticket synchronization flow."""
    # Pre-check feature permissions
    if not check_feature_permission("Sync Jira Ticket", "BROWSE_PROJECTS"):
        return

    issue_key = input("\n👉 Enter Jira Ticket Key to sync (e.g. PROJ-123): ").strip().upper()
    if not issue_key:
        print("[!] Ticket key cannot be empty.")
        return

    print(f"\n⏳ Syncing ticket {issue_key}...")
    service = SyncService()
    result = service.sync(issue_key)

    if result.success:
        print("\n" + "=" * 65)
        print(f"🎉 TICKET SYNCED SUCCESSFULLY: {result.key}")
        print(f"📄 Ticket File    : {result.ticket_file}")
        print(f"📜 Changelog File : {result.history_file}")
        print(f"🖼️  Assets Download: {result.assets_downloaded} image(s)")
        print(f"📊 Catalog Index  : {INDEX_FILE}")
        print("=" * 65)
        print("💡 Tip: AI Agents can now read ticket.md and history.md for full context.")
    else:
        print(f"\n❌ Sync failed: {result.message}")
        print("🔍 See error stack trace in: logs/app.log")


def handle_list_tickets() -> None:
    """Displays table of all synced tickets."""
    tickets = list_indexed_tickets()
    if not tickets:
        print("\nℹ️  No tickets have been synced yet in .ai-context/tickets/")
        return

    print(f"\n📋 SYNCHRONIZED TICKETS CATALOG ({len(tickets)} tickets):")
    print("-" * 75)
    print(f"{'Key':<12} | {'Type':<10} | {'Status':<14} | {'Assignee':<18} | {'Assets'}")
    print("-" * 75)
    for t in tickets:
        key = t.get("key", "")
        t_type = t.get("type", "")[:10]
        status = t.get("status", "")[:14]
        assignee = t.get("assignee", "")[:18]
        assets = t.get("assets_count", 0)
        print(f"{key:<12} | {t_type:<10} | {status:<14} | {assignee:<18} | {assets} image(s)")
    print("-" * 75)
    print(f"Full catalog index: {INDEX_FILE}\n")


def handle_check_account() -> None:
    """Verifies existing credentials or offers to switch account."""
    config = load_config()
    if not config.is_configured:
        print("\n⚠️ No saved Jira credentials found.")
        prompt_login()
        return

    client = JiraClient(config)
    try:
        user = client.verify_account()
        perms = client.check_permissions(["BROWSE_PROJECTS"])
        SESSION["user"] = user
        SESSION["permissions"] = perms
        print_account_permissions_summary(user, perms)
    except Exception as e:
        print(f"❌ Verification failed: {e}")

    choice = input("\nDo you want to switch account? (y/n) [n]: ").strip().lower()
    if choice in ("y", "yes"):
        prompt_login()


def handle_run_mcp_server() -> None:
    """Launches MCP server in stdio mode."""
    if not check_feature_permission("Start MCP Server", "BROWSE_PROJECTS"):
        return

    print("\n🚀 Starting Jira Sync MCP Server over stdio...")
    print("AI Agents (Cursor, Claude Desktop, Antigravity) can connect using: python server.py")
    from server import main as run_mcp
    run_mcp()


def main() -> None:
    """Main CLI event loop."""
    print_banner()

    # Strictly enforce authentication before accessing the menu
    config = load_config()
    authenticated = False

    if config.is_configured:
        print("⏳ Verifying saved Jira credentials from .env...")
        client = JiraClient(config)
        try:
            user = client.verify_account()
            perms = client.check_permissions(["BROWSE_PROJECTS"])
            SESSION["user"] = user
            SESSION["permissions"] = perms
            print_account_permissions_summary(user, perms)
            authenticated = True
        except Exception as e:
            print(f"⚠️ Saved credentials failed verification: {e}")
            authenticated = False

    while not authenticated:
        print("\n🔑 Please log in to your Jira account to proceed.")
        ok = prompt_login()
        if ok:
            authenticated = True
            break
        retry = input("Login failed. Do you want to try again? (y/n) [y]: ").strip().lower()
        if retry in ("n", "no", "exit", "quit", "q"):
            print("\n👋 Exiting. Authentication is required to use this tool.\n")
            sys.exit(1)

    while True:
        print("\n" + "=" * 75)
        print("                                ACTION MENU")
        print("=" * 75)
        print(" [1] Sync Jira Ticket")
        print("     ↳ Required: BROWSE_PROJECTS (or read:jira-work, read:attachment)")
        print(" [2] List Synced Tickets")
        print("     ↳ Required: Local storage only (No Jira permissions needed)")
        print(" [3] Check / Switch Jira Account")
        print("     ↳ Required: read:me / Basic Auth")
        print(" [4] Start MCP Server (Stdio Mode)")
        print("     ↳ Required: BROWSE_PROJECTS (or read:jira-work, read:attachment)")
        print(" [0] Exit")
        print("=" * 75)

        choice = input("👉 Select action (0-4): ").strip()

        if choice == "1":
            handle_sync_ticket()
        elif choice == "2":
            handle_list_tickets()
        elif choice == "3":
            handle_check_account()
        elif choice == "4":
            handle_run_mcp_server()
            break
        elif choice in ("0", "exit", "quit", "q"):
            print("\n👋 Goodbye!\n")
            break
        else:
            print("[!] Invalid option. Please select a number between 0 and 4.")


if __name__ == "__main__":
    main()
