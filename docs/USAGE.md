# Usage

## 1. Install and log in

```bash
pip install -r requirements.txt
python utils/env_check.py          # pre-flight: Python 3.10+ and dependencies
python cli.py                      # first run asks for Jira URL, email, API token, then saves .env
```

Token and permissions: [JIRA_ACCESS.md](JIRA_ACCESS.md).

## 2. CLI

At start the CLI verifies the saved credentials (or asks for URL, email, and token: Enter keeps the saved value), audits `BROWSE_PROJECTS`, then shows the menu:

| Menu | Action |
|---|---|
| `[1]` Sync Jira Ticket | key (`PROJ-123`) or ticket URL → files in `AI_CONTEXT_DIR` |
| `[2]` List Synced Tickets | local catalog, no Jira call |
| `[3]` Check / Switch Jira Account | re-verify, or log in as someone else |
| `[4]` Start MCP Server | runs the stdio server in this terminal (normally the AI client starts it) |
| `[0]` Exit | |

A missing `BROWSE_PROJECTS` is a warning with a `y/n` prompt, not a block. Behavior details: [FEATURES.md](FEATURES.md).

## 3. MCP server

The AI client starts `python <JIRA_SYNC_PATH>/server.py` over stdio. Client-by-client setup: [AI_AGENT_SETUP.md](AI_AGENT_SETUP.md).

| Tool | Does |
|---|---|
| `jira_sync_ticket(issue_key)` | syncs the ticket, returns absolute paths of `ticket.md` / `history.md` |
| `jira_list_synced()` | lists synced tickets with absolute paths (offline) |
| `jira_check_connection()` | checks credentials and shows the user |

Full contract (arguments, annotations): [AGENTS.md §4](../AGENTS.md#4-mcp-tools-reference).

Example result:
```
✅ Ticket PROJ-123 synchronized successfully!
- Ticket Details & Description : <WORKSPACE>/.ai-context/tickets/PROJ-123/ticket.md
- Changelog & Evolution History : <WORKSPACE>/.ai-context/tickets/PROJ-123/history.md
- Downloaded Images/Diagrams    : 2 image(s)
- Master Catalog Index          : <WORKSPACE>/.ai-context/INDEX.md
```

## 4. Output

```
<AI_CONTEXT_DIR>/                   # default <JIRA_SYNC_PATH>/.ai-context; set AI_CONTEXT_DIR to move it
├── INDEX.md                        # table of all synced tickets
├── catalog.json                    # machine-readable catalog
└── tickets/PROJ-123/
    ├── ticket.md                   # YAML frontmatter + description + images + relations
    ├── history.md                  # changelog, newest first
    └── assets/                     # downloaded images
```

The format is a contract: [AI_CONTEXT_FORMAT.md](AI_CONTEXT_FORMAT.md). Ticket data is internal: if `AI_CONTEXT_DIR` points into another repository, git-ignore it there ([SECURITY.md](SECURITY.md)).

## 5. Inside an MCP hub

Spawn `python <JIRA_SYNC_PATH>/server.py` as a stdio child and inject `JIRA_*` / `CENTRAL_CONFIG_PATH` / `AI_CONTEXT_DIR`, or mount it in a Python hub with `register_jira_tools(app)`: [PARENT_MCP_GUIDE.md](PARENT_MCP_GUIDE.md).

## 6. Debugging

Everything (requests, file writes, tracebacks with `file:line in function`) goes to `logs/app.log` (rotating, git-ignored). Common errors: [JIRA_ACCESS.md §5](JIRA_ACCESS.md#5-troubleshooting).

## 7. Development

```bash
python -m unittest discover tests  # offline, < 2 s, includes the public-repo hygiene check
```

Rules for every change are in [AGENTS.md](../AGENTS.md) and [SECURITY.md](SECURITY.md).
