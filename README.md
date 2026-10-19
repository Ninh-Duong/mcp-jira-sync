# Jira Ticket Sync for AI Agents (`jira_sync_ticket`)

A local MCP server and interactive CLI that turns a Jira Cloud ticket into Markdown + images an AI agent can read: description (ADF → Markdown), screenshots, change history, and related issues. Read-only on Jira. Built to run standalone or as a child of an MCP hub.

When an agent works on `PROJ-123`, one call to `jira_sync_ticket` produces:

```
<AI_CONTEXT_DIR>/                   # default <repo>/.ai-context, movable into the agent's workspace
├── INDEX.md                        # table of all synced tickets
├── catalog.json                    # machine-readable catalog
└── tickets/PROJ-123/
    ├── ticket.md                   # YAML frontmatter + description + images + relations
    ├── history.md                  # changelog, newest first
    └── assets/                     # downloaded images
```

Format contract: [docs/AI_CONTEXT_FORMAT.md](docs/AI_CONTEXT_FORMAT.md).

---

## Quick start

Requires Python **3.10+** (Windows, macOS, Linux).

```bash
pip install -r requirements.txt
python utils/env_check.py          # pre-flight: Python + dependencies
python cli.py                      # log in once (saves .env), then use the menu
```

Token: https://id.atlassian.com/manage-profile/security/api-tokens. Permissions and scopes: [docs/JIRA_ACCESS.md](docs/JIRA_ACCESS.md).

### CLI

On start the CLI verifies the saved credentials (or asks for URL, email, and token), audits `BROWSE_PROJECTS`, then shows:

| Menu | Action |
|---|---|
| `[1]` Sync Jira Ticket | key (`PROJ-123`) or ticket URL → files above |
| `[2]` List Synced Tickets | local catalog, no Jira call |
| `[3]` Check / Switch Jira Account | re-verify, or log in as someone else |
| `[4]` Start MCP Server | runs the stdio server in this terminal (normally the AI client starts it) |
| `[0]` Exit | |

### MCP server

```json
{
  "mcpServers": {
    "jira-sync": {
      "command": "python",
      "args": ["/absolute/path/to/jira_sync_ticket/server.py"],
      "env": { "AI_CONTEXT_DIR": "/absolute/path/to/your-workspace/.ai-context" }
    }
  }
}
```

Per-client steps (Claude Code, Claude Desktop, Cursor, VS Code, Antigravity, Codex): [docs/AI_AGENT_SETUP.md](docs/AI_AGENT_SETUP.md). Easiest: give that file to your agent.

| Tool | Does |
|---|---|
| `jira_sync_ticket(issue_key)` | syncs the ticket, returns absolute paths of `ticket.md` / `history.md` |
| `jira_list_synced()` | lists synced tickets with absolute paths (offline) |
| `jira_check_connection()` | checks credentials and shows the user |

Example result:
```
✅ Ticket PROJ-123 synchronized successfully!
- Ticket Details & Description : <WORKSPACE>/.ai-context/tickets/PROJ-123/ticket.md
- Changelog & Evolution History : <WORKSPACE>/.ai-context/tickets/PROJ-123/history.md
- Downloaded Images/Diagrams    : 2 image(s)
- Master Catalog Index          : <WORKSPACE>/.ai-context/INDEX.md
```

### Inside an MCP hub

Spawn `python server.py` as a stdio child and inject `JIRA_*` / `CENTRAL_CONFIG_PATH` / `AI_CONTEXT_DIR`, or mount it in a Python hub with `register_jira_tools(app)`. See [docs/PARENT_MCP_GUIDE.md](docs/PARENT_MCP_GUIDE.md).

---

## Debugging

Everything (requests, file writes, tracebacks with `file:line in function`) goes to `logs/app.log`, rotating, git-ignored. Common errors: [docs/JIRA_ACCESS.md §5](docs/JIRA_ACCESS.md#5-troubleshooting).

## Development

```bash
python -m unittest discover tests  # offline, < 2 s
```

Rules for every change (human or agent) are in [AGENTS.md](AGENTS.md), and docs move with the code.

## Documentation

| Doc | For |
|---|---|
| [AGENTS.md](AGENTS.md) | **Start here when changing code**: rules, code map, tool reference, anti-drift rule |
| [docs/FEATURES.md](docs/FEATURES.md) | What each feature does and does not do (the spec) |
| [docs/AI_CONTEXT_FORMAT.md](docs/AI_CONTEXT_FORMAT.md) | Output contract: `ticket.md`, `history.md`, `catalog.json` |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Modules, sync pipeline, Jira endpoint strategy |
| [docs/STANDARDS.md](docs/STANDARDS.md) | Coding, MCP tool, error, logging, and test standards |
| [docs/JIRA_ACCESS.md](docs/JIRA_ACCESS.md) | Tokens, permissions, config priority, env variables |
| [docs/AI_AGENT_SETUP.md](docs/AI_AGENT_SETUP.md) | Agent-executable client setup |
| [docs/PARENT_MCP_GUIDE.md](docs/PARENT_MCP_GUIDE.md) | Hub integration (subprocess, in-process, programmatic) |
| [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) | Why each dependency exists, what is excluded |
| [docs/BACKLOG.md](docs/BACKLOG.md) | Known issues and limits |
