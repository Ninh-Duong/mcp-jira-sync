# Features (the spec)

This is the list of what the project does, and **does not** do. An agent adding behavior must first add or extend a block here (see [AGENTS.md §2](../AGENTS.md#2-how-to-add-a-feature-in-this-order)). Anything not listed is out of scope until it is written down here.

**Product goal (one line)**: let an AI agent read the full, current context of one Jira ticket (requirements, images, history, relations) before it works on it, with **read-only** access to Jira and an **encrypted** local cache that only a logged-in user can open.

Typical use, through mcp-hub: `/mcp-hub mcp-jira-sync PROJ-123 read this ticket first, then we discuss the feature`. The agent syncs the ticket (F1), reads it (F8), lists every use case, and waits.

**Global non-goals**:
- No writes to Jira (no comments, transitions, field edits).
- No search, JQL, or bulk sync of many tickets.
- No database, vector store, or embeddings: plain files only.
- No Jira Server/Data Center specifics: Jira Cloud REST v3 is the target.
- No OAuth flow: Basic auth with an Atlassian API token (classic or scoped).

---

## F1. Sync one ticket

| | |
|---|---|
| Entry points | MCP `jira_sync_ticket(issue_key)` · CLI menu `[1]` |
| Core | `SyncService.sync` ([core/sync_service.py](../core/sync_service.py)) |
| Output | [AI_CONTEXT_FORMAT.md](AI_CONTEXT_FORMAT.md) |
| Tests | `TestSyncServiceWithMock.test_full_sync_flow`, `test_sync_key_from_url`, `test_sync_refuses_without_access`, `TestContracts.test_issue_key_extraction`, `test_frontmatter_is_valid_and_complete` |

Behavior rules:
1. Input is a bare key (`PROJ-123`, `my_proj-1`, case-insensitive) or a URL containing `/browse/KEY` or `selectedIssue=KEY`. Anything else returns `success=False` with no Jira call. A hostname such as `team-2.atlassian.net` is never taken for a key.
2. Unconfigured credentials return `success=False` with a message to log in. Nothing is written.
3. The access gate (F7) runs first; when it refuses, the message starts with `No access:` and nothing is fetched or written.
4. One `GET /rest/api/3/issue/{key}?expand=changelog,names` (with endpoint fallback, see [ARCHITECTURE.md](ARCHITECTURE.md#3-jira-access-strategy)).
5. Image attachments download **into memory** and are written encrypted to `assets/<file>.enc`; non-image attachments are listed only.
6. Description ADF → Markdown; `ticket.md.enc` and `history.md.enc` are fully rewritten (same Jira state gives the same plaintext; the ciphertext differs each time).
7. The encrypted catalog is updated. Plaintext files left by older versions (`ticket.md`, `history.md`, unencrypted assets, `catalog.json`, `INDEX.md`) are deleted.
8. Errors never raise out of `sync()`: `JiraApiError` / `NoAccessError` → its message (404 not found / 403 forbidden / 401 auth / `No access:`); anything else → `Unexpected error: ...`, with the stack trace in `logs/app.log`.
9. The MCP reply holds the key and the image count, not file paths (the files are unreadable without F8).

Non-goals: no download of non-image files (PDF, docx, zip), no comments, no worklogs, no custom-field mapping (only the fields in the frontmatter table).

## F2. Asset purge on re-sync

| | |
|---|---|
| Entry points | part of F1 |
| Tests | `TestSyncServiceWithMock.test_sync_purges_obsolete_assets` |

Rules: after downloading, delete every file in `tickets/<KEY>/assets/` whose name is not `<current image attachment>.enc` (this also removes plaintext images from older versions); remove the folder if it is empty. Outside `assets/`, only the legacy plaintext files of F1 rule 7 are deleted.

Non-goals: no purge of whole ticket folders or catalog entries for tickets deleted in Jira.

## F3. List synced tickets

| | |
|---|---|
| Entry points | MCP `jira_list_synced()` · CLI menu `[2]` |
| Core | `list_indexed_tickets(fernet)` ([core/indexer.py](../core/indexer.py)) |
| Tests | `TestSyncServiceWithMock.test_full_sync_flow`, `TestReadTools.test_reads_refused_without_access` |

Rules: passes the access gate (F7, one Jira call), then decrypts `catalog.json.enc`; sorted by `jira_updated_at` desc. Each line: key, summary, status, assignee, `synced_at`. No file paths.

Non-goals: no filtering or search parameters until an agent needs them (then add them here first).

## F4. Account login, check, and switch

| | |
|---|---|
| Entry points | CLI at start (required before the menu) and menu `[3]` · MCP `jira_check_connection()` (check only) |
| Core | `JiraClient.verify_account`, `check_permissions`, `save_config` |
| Tests | `TestContracts.test_config_priority_env_then_central_then_dotenv`, `test_save_config_keeps_other_env_lines` |

Rules:
1. The CLI prints the required permissions and scopes ([JIRA_ACCESS.md](JIRA_ACCESS.md)), asks for URL, email, and token (Enter keeps the saved value), verifies, audits `BROWSE_PROJECTS`, then saves to `.env`, keeping every other line in it. When no source has a `JIRA_AI_CONTEXT_KEY` yet, it also writes a new one (F7); an existing key is never replaced, so switching account keeps old data readable.
2. A missing `BROWSE_PROJECTS` is a **warning** with a y/n prompt, not a block (the global check can be false while one project still grants access).
3. The MCP tool never asks for or saves credentials; it tells the agent to have the user run `python cli.py` (standalone; under mcp-hub fix the `jira` block in the Hub private config).
4. Credential priority: process env > central JSON (`CENTRAL_CONFIG_PATH`) > `.env`.

Non-goals: no multi-account switching inside the MCP server, no keychain storage.

## F5. MCP server (standalone and mountable)

| | |
|---|---|
| Entry points | `python server.py` · CLI menu `[4]` · `mcp-jira-sync` script · `register_jira_tools(app, prefix)` |
| Tests | `TestContracts.test_tools_mount_with_prefix` |

Rules: stdio transport; sends `jira_instructions()` on connect; 5 tools with annotations ([AGENTS.md §4](../AGENTS.md#4-mcp-tools-reference)); importing `server` has no side effects besides logger setup; nothing is written to stdout except JSON-RPC. Works with mcp 1.x (`FastMCP`) and 2.x (`MCPServer`).

Non-goals: no HTTP/SSE transport, no MCP resources or prompts. The `/mcp-hub mcp-jira-sync <task>` command is the hub's prompt (it loads the hub's `docs/mcps/mcp-jira-sync.md`), so this server needs none.

## F6. Pre-flight environment check

| | |
|---|---|
| Entry points | `python utils/env_check.py` · automatically when running `cli.py` or `server.py` as a script |
| Core | `verify_environment` ([utils/env_check.py](../utils/env_check.py)) |

Rules: Python ≥ 3.10 and `mcp`, `httpx`, `dotenv`, `cryptography` importable; on failure, print the fix (`pip install -r requirements.txt`) to **stderr** and exit 1.

## F7. Encrypted `.ai-context/` and the access gate

| | |
|---|---|
| Entry points | every write (F1) and read (F3, F8, CLI `[5]`) |
| Core | `unlock`, `write_encrypted`, `read_encrypted`, `NoAccessError` ([core/vault.py](../core/vault.py)), the only module that uses the cipher |
| Format | [AI_CONTEXT_FORMAT.md](AI_CONTEXT_FORMAT.md) |
| Tests | `TestSyncServiceWithMock.test_full_sync_flow` (nothing readable on disk), `test_sync_refuses_without_access`, `test_sync_purges_obsolete_assets`, `TestReadTools.test_reads_refused_without_access`, `TestContracts.test_save_config_keeps_other_env_lines` |

Purpose: someone who opens the repository or the `.ai-context/` folder sees only ciphertext. Ticket content is readable only through this server's tools or the CLI, by a user whose Jira login works right now.

Rules:
1. Every file under `.ai-context/` is a Fernet token (`cryptography`: AES-128-CBC + HMAC-SHA256, authenticated) named `<name>.enc`. Plaintext never touches the disk: images are encrypted from memory.
2. The key is `JIRA_AI_CONTEXT_KEY` (process env > central JSON `ai_context_key` > `.env`, the same priority as the token). The CLI writes one at the first login. The server never writes it, so under a hub (`PYTHON_DOTENV_DISABLED=1`) it must be injected.
3. The gate `unlock(config)` passes only when the key is set and valid **and** `verify_account()` succeeds right now. It runs on every sync, read, and list call, with no cache.
4. A refusal, or a file that fails to decrypt (wrong key, edited file), gives a message starting with `No access:`. Agents are told to stop and send the user to `python cli.py` (standalone; under mcp-hub fix the `jira` block in the Hub private config).
5. The key and decrypted content are never logged. The log records only the error type of a failed access check.

Non-goals: no per-user or per-project keys (one key per `.ai-context/`; share it with teammates who should read the same folder), no key rotation (a lost or changed key means deleting `.ai-context/` and syncing again), no hidden file or folder names (ticket keys and image names stay visible), no migration of old plaintext folders (re-sync or delete them).

## F8. Read a synced ticket

| | |
|---|---|
| Entry points | MCP `jira_read_ticket(issue_key)`, `jira_read_asset(issue_key, filename)` · CLI menu `[5]` (prints `ticket.md`) |
| Core | `read_synced_file(issue_key, name, fernet)` ([core/sync_service.py](../core/sync_service.py)) |
| Tests | `TestReadTools` |

Purpose: the agent gets the ticket's text and screenshots in its context, so it misses no use case and the user does not have to retell it.

Rules:
1. Both tools pass the gate (F7) first.
2. `jira_read_ticket` returns `✅ <KEY>: ...` then the decrypted `ticket.md`, a `---` line, and `history.md`.
3. `jira_read_asset` returns one MCP image block (base64, MIME from the extension). It accepts the file name as written in `ticket.md`, with or without `assets/`. Only `IMAGE_MIME_TYPES` extensions are served.
4. A name that resolves outside `tickets/<KEY>/` is refused. A ticket that was never synced returns `❌ ... Call jira_sync_ticket first.`
5. Reading never calls Jira for ticket data (only the gate's `/myself`); call `jira_sync_ticket` to refresh.

Non-goals: no paging or search inside a ticket, no automatic sync on read (the hub treats sync as a write), no non-image attachments.
