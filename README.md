# Jira Ticket Sync for AI Agents (`jira_sync_ticket`)

A modular, local Model Context Protocol (MCP) server and interactive CLI designed to synchronize Jira tickets into structured Markdown documents and local image assets for AI Agents (such as Cursor, Claude Desktop, Antigravity, and Windsurf).

---

## 💡 What This Project Does

When an AI Agent is tasked with solving a Jira issue (e.g. `PROJ-123`), this tool:
1. **Fetches complete ticket data** via Jira Cloud REST API v3 using an API token.
2. **Converts description from ADF** (Atlassian Document Format) to clean, standard Markdown.
3. **Extracts change history (Changelog)** chronologically into `history.md` so AI understands how requirements evolved.
4. **Downloads attached screenshots & diagrams** into `.ai-context/tickets/<KEY>/assets/`.
5. **Generates machine-readable context** (`ticket.md` with YAML frontmatter).
6. **Maintains a global catalog** (`.ai-context/INDEX.md` and `catalog.json`) for multi-agent discovery.

---

## 📁 Repository Structure

```
jira_sync_ticket/
├── .env.example          # Environment template
├── .env                  # Local credentials (git-ignored)
├── .gitignore            # Ignores .env, logs/, .ai-context/, and virtualenv
├── requirements.txt      # Minimal dependencies (mcp, httpx, python-dotenv)
├── pyproject.toml        # Standard Python packaging
├── README.md             # Project documentation
├── rules.md              # AI Agent architectural rules & constraints
├── logs/                 # Runtime logs for AI debugging (git-ignored)
│   └── app.log           # Rotating log file with function names & stack traces
├── core/
│   ├── config.py         # 100% relative path resolution & settings
│   ├── adf_parser.py     # Recursive ADF to Markdown converter
│   ├── jira_client.py    # Jira REST API client & asset downloader
│   ├── sync_service.py   # Core synchronization pipeline
│   └── indexer.py        # INDEX.md and catalog.json generator
├── utils/
│   ├── env_check.py      # Pre-flight runtime and dependency check
│   └── logger.py         # Dual console & rotating file logger
├── cli.py                # Interactive CLI menu & login flow
└── server.py             # Local MCP Server (stdio transport for AI Agents)
```

---

## 🚀 Quick Setup

### 1. Requirements
- Python **3.10+** (Tested on Windows, macOS, Linux).

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

Verify environment readiness:
```bash
python utils/env_check.py
```

### 3. Required Jira Permissions & Scopes (Latest Atlassian Standard)
When using a **Personal API Token** (Basic Auth), the token automatically inherits the permissions of your Atlassian user. Ensure your user has:
- **Project Permission Key**:
  - `BROWSE_PROJECTS`: Ability to browse projects, search issues, and view issue details.

When using an **OAuth 2.0 / Atlassian App Token**, ensure the following **Granular Scopes** are granted:
- `read:me`: Read current user profile (`/rest/api/3/myself`)
- `read:jira-work`: Read project metadata and permission validation (classic scope covering all issue reads)
- `read:issue-details:jira`: Read ticket description, summary, and fields
- `read:attachment:jira`: Access and download attached images and screenshots
- `read:issue.changelog:jira`: Read ticket changelog and requirement edit history (NOT `read:audit-log:jira`)

Generate your Personal API Token at: [Atlassian Security API Tokens](https://id.atlassian.net/manage-profile/security/api-tokens)

---

## 🖥️ Usage

### Option A: Interactive CLI
Run the CLI:
```bash
python cli.py
```
- **First run**: Prompts for your Jira URL (e.g. `https://your-domain.atlassian.net`), email, and API token, tests authentication and permissions, and saves to `.env`.
- **Menu**:
  - `[1] Sync Jira Ticket`: Enter a key (e.g. `PROJ-123` or full ticket URL) to download full context.
  - `[2] List Synced Tickets`: View all locally indexed tickets.
  - `[3] Check / Switch Jira Account`: Re-verify credentials or change user.
  - `[4] Start MCP Server`: Run stdio MCP server directly.
  - `[0] Exit`.

### Option B: Local MCP Server for AI Agents
Run the server:
```bash
python server.py
```

#### Client Configuration (e.g., Claude Desktop, Cursor, Antigravity)

**In Claude Desktop (`claude_desktop_config.json`)**:
```json
{
  "mcpServers": {
    "jira-sync-ticket": {
      "command": "python",
      "args": ["/absolute/path/to/jira_sync_ticket/server.py"]
    }
  }
}
```

**In Cursor (`.cursor/mcp.json`)**:
```json
{
  "mcpServers": {
    "jira-sync": {
      "command": "python",
      "args": ["server.py"]
    }
  }
}
```

#### Exposed MCP Tools:
- `jira_sync_ticket(issue_key)`: Synchronizes ticket, downloads images, and returns Markdown path.
- `jira_list_synced()`: Returns summary of all tickets in local index.
- `jira_check_connection()`: Validates Jira API connectivity.

---

## 🗄️ Output Data Format (`.ai-context/`)

```
.ai-context/
├── INDEX.md                     # Master table of all synced tickets
├── catalog.json                 # Machine-readable JSON catalog
└── tickets/
    └── PROJ-123/
        ├── ticket.md            # YAML frontmatter + description + image links
        ├── history.md           # Chronological changelog timeline
        └── assets/              # Local image files & UI screenshots
            └── screenshot.png
```

---

## 🩺 Debugging for AI Agents

All operational details, API requests, and exception tracebacks are logged to:
```
logs/app.log
```
If a sync fails, AI Agents can inspect `logs/app.log` to view the exact line number, request URL, and error traceback to diagnose and resolve issues immediately.
