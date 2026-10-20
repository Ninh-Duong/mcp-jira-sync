# Usage

## 1. Install and log in

```bash
pip install -r requirements.txt
python utils/env_check.py          # pre-flight: Python 3.10+ and dependencies
python cli.py                      # first run asks for Jira URL, email, API token, then saves .env
```

Token and permissions: [JIRA_ACCESS.md](JIRA_ACCESS.md). Under mcp-hub the hub's venv and private config are used instead: [README.md](../README.md#running-under-mcp-hub).

## 2. CLI

At start the CLI verifies the saved credentials (or asks for URL, email, and token: Enter keeps the saved value), audits `BROWSE_PROJECTS`, then shows the menu. The first login also writes `JIRA_AI_CONTEXT_KEY` to `.env` (the key that encrypts `.ai-context/`, see [JIRA_ACCESS.md](JIRA_ACCESS.md#the-encryption-key)).

| Menu | Action |
|---|---|
| `[1]` Sync Jira Ticket | key (`PROJ-123`) or ticket URL → encrypted files in `AI_CONTEXT_DIR` |
| `[2]` List Synced Tickets | decrypts the local catalog (needs a working login) |
| `[3]` Check / Switch Jira Account | re-verify, or log in as someone else (the key is kept) |
| `[4]` Start MCP Server | runs the stdio server in this terminal (normally the AI client starts it) |
| `[5]` Read Synced Ticket | decrypts and prints `ticket.md` (needs a working login) |
| `[0]` Exit | |

A missing `BROWSE_PROJECTS` is a warning with a `y/n` prompt, not a block. Behavior details: [FEATURES.md](FEATURES.md).

## 3. MCP server

The AI client starts `python <JIRA_SYNC_PATH>/server.py` over stdio. Client-by-client setup: [AI_AGENT_SETUP.md](AI_AGENT_SETUP.md).

| Tool | Does |
|---|---|
| `jira_sync_ticket(issue_key)` | fetches the ticket into the encrypted cache (the only tool that writes) |
| `jira_read_ticket(issue_key)` | returns the decrypted `ticket.md` + `history.md` |
| `jira_read_asset(issue_key, filename)` | returns one screenshot as an image |
| `jira_list_synced()` | lists synced tickets |
| `jira_check_connection()` | checks credentials and shows the user |

Every tool except `jira_check_connection` passes the access gate first: key set **and** a Jira login that works now, else `❌ No access: …`. Full contract (arguments, annotations): [AGENTS.md §4](../AGENTS.md#4-mcp-tools-reference).

Typical agent flow (what `jira_instructions()` tells it, and what `/mcp-hub mcp-jira-sync PROJ-123 read this ticket` triggers through a hub):
```
jira_sync_ticket("PROJ-123")   → ✅ Ticket PROJ-123 synchronized (encrypted in .ai-context/). - Images: 2
jira_read_ticket("PROJ-123")   → ✅ PROJ-123: ticket.md then history.md ... (full Markdown)
jira_read_asset("PROJ-123", "login-error.png")  → image
→ the agent lists goal, use cases, acceptance criteria, edge cases, open questions, and waits for you
```

## 4. Output

```
<AI_CONTEXT_DIR>/                   # default <JIRA_SYNC_PATH>/.ai-context; set AI_CONTEXT_DIR to move it
├── catalog.json.enc                # catalog of synced tickets
└── tickets/PROJ-123/
    ├── ticket.md.enc               # YAML frontmatter + description + images + relations
    ├── history.md.enc              # changelog, newest first
    └── assets/<file>.enc           # downloaded images
```

Every file is encrypted: opening one shows only a Fernet token. The format is a contract: [AI_CONTEXT_FORMAT.md](AI_CONTEXT_FORMAT.md). Upgrading from a plaintext version: re-sync your tickets (their plaintext files are deleted) or delete `.ai-context/`. File names stay readable, so keep the folder git-ignored if ticket keys are private ([SECURITY.md](SECURITY.md)).

## 5. Inside an MCP hub

Spawn `python <JIRA_SYNC_PATH>/server.py` as a stdio child and inject `JIRA_*` / `CENTRAL_CONFIG_PATH` / `AI_CONTEXT_DIR`, or mount it in a Python hub with `register_jira_tools(app)`: [PARENT_MCP_GUIDE.md](PARENT_MCP_GUIDE.md). mcp-hub specifics: [README.md](../README.md#running-under-mcp-hub).

## 6. Debugging

Everything (requests, file writes, tracebacks with `file:line in function`) goes to `logs/app.log` (rotating, git-ignored). Common errors: [JIRA_ACCESS.md §5](JIRA_ACCESS.md#5-troubleshooting).

## 7. Development

```bash
python -m unittest discover tests  # offline, < 2 s, includes the public-repo hygiene check
```

Rules for every change are in [AGENTS.md](../AGENTS.md) and [SECURITY.md](SECURITY.md).
