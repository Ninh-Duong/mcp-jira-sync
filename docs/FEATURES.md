# Features (the spec)

This is the list of what the project does, and **does not** do. An agent adding behavior must first add or extend a block here (see [AGENTS.md §2](../AGENTS.md#2-how-to-add-a-feature-in-this-order)). Anything not listed is out of scope until it is written down here.

**Product goal (one line)**: give an AI agent the full, current context of one Jira ticket (requirements, images, history, relations) as local Markdown, with **read-only** access to Jira.

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
| Tests | `TestSyncServiceWithMock.test_full_sync_flow`, `test_sync_key_from_url`, `TestContracts.test_issue_key_extraction`, `test_frontmatter_is_valid_and_complete` |

Behavior rules:
1. Input is a bare key (`PROJ-123`, `my_proj-1`, case-insensitive) or a URL containing `/browse/KEY` or `selectedIssue=KEY`. Anything else returns `success=False` with no Jira call. A hostname such as `team-2.atlassian.net` is never taken for a key.
2. Unconfigured credentials return `success=False` with a message to log in. Nothing is written.
3. One `GET /rest/api/3/issue/{key}?expand=changelog,names` (with endpoint fallback, see [ARCHITECTURE.md](ARCHITECTURE.md#3-jira-access-strategy)).
4. Image attachments download into `assets/`; non-image attachments are listed only.
5. Description ADF → Markdown; `ticket.md` and `history.md` are fully rewritten (idempotent: the same Jira state gives the same files).
6. The catalog and `INDEX.md` are updated.
7. Errors never raise out of `sync()`: `JiraApiError` → its message (404 not found / 403 forbidden / 401 auth); anything else → `Unexpected error: ...`, with the stack trace in `logs/app.log`.

Non-goals: no download of non-image files (PDF, docx, zip), no comments, no worklogs, no custom-field mapping (only the fields in the frontmatter table).

## F2. Asset purge on re-sync

| | |
|---|---|
| Entry points | part of F1 |
| Tests | `TestSyncServiceWithMock.test_sync_purges_obsolete_assets` |

Rules: after downloading, delete every file in `tickets/<KEY>/assets/` whose name is not a current image attachment; remove the folder if it is empty. Files outside `assets/` are never deleted.

Non-goals: no purge of whole ticket folders or catalog entries for tickets deleted in Jira.

## F3. List synced tickets

| | |
|---|---|
| Entry points | MCP `jira_list_synced()` · CLI menu `[2]` |
| Core | `list_indexed_tickets()` ([core/indexer.py](../core/indexer.py)) |
| Tests | covered indirectly by sync tests; extend when the output changes |

Rules: reads `catalog.json` only (no Jira call, works offline), sorted by `jira_updated_at` desc. MCP output gives absolute `ticket.md` paths.

Non-goals: no filtering or search parameters until an agent needs them (then add them here first).

## F4. Account login, check, and switch

| | |
|---|---|
| Entry points | CLI at start (required before the menu) and menu `[3]` · MCP `jira_check_connection()` (check only) |
| Core | `JiraClient.verify_account`, `check_permissions`, `save_config` |
| Tests | `TestContracts.test_config_priority_env_then_central_then_dotenv`, `test_save_config_keeps_other_env_lines` |

Rules:
1. The CLI prints the required permissions and scopes ([JIRA_ACCESS.md](JIRA_ACCESS.md)), asks for URL, email, and token (Enter keeps the saved value), verifies, audits `BROWSE_PROJECTS`, then saves to `.env`, keeping every other line in it.
2. A missing `BROWSE_PROJECTS` is a **warning** with a y/n prompt, not a block (the global check can be false while one project still grants access).
3. The MCP tool never asks for or saves credentials; it tells the agent to have the user run `python cli.py`.
4. Credential priority: process env > central JSON (`CENTRAL_CONFIG_PATH`) > `.env`.

Non-goals: no multi-account switching inside the MCP server, no keychain storage.

## F5. MCP server (standalone and mountable)

| | |
|---|---|
| Entry points | `python server.py` · CLI menu `[4]` · `mcp-jira-sync` script · `register_jira_tools(app, prefix)` |
| Tests | `TestContracts.test_tools_mount_with_prefix` |

Rules: stdio transport; sends `jira_instructions()` on connect; 3 tools with annotations ([AGENTS.md §4](../AGENTS.md#4-mcp-tools-reference)); importing `server` has no side effects besides logger setup; nothing is written to stdout except JSON-RPC. Works with mcp 1.x (`FastMCP`) and 2.x (`MCPServer`).

Non-goals: no HTTP/SSE transport, no MCP resources or prompts yet (add them here first if a hub needs them).

## F6. Pre-flight environment check

| | |
|---|---|
| Entry points | `python utils/env_check.py` · automatically when running `cli.py` or `server.py` as a script |
| Core | `verify_environment` ([utils/env_check.py](../utils/env_check.py)) |

Rules: Python ≥ 3.10 and `mcp`, `httpx`, `dotenv` importable; on failure, print the fix (`pip install -r requirements.txt`) to **stderr** and exit 1.
