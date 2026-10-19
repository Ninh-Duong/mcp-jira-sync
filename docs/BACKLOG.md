# Backlog (known issues and limits)

From the 2026-10-20 review. Not fixed yet, in rough priority order. Before fixing one: write its spec in [FEATURES.md](FEATURES.md) if behavior changes, add a failing test, then remove the row here.

## Fixed in the 2026-10-20 review (for history)

| Issue | Fix |
|---|---|
| `core/sync_service.py` frontmatter f-string was a SyntaxError on Python 3.10/3.11 | `json.dumps` per value via `FRONTMATTER_KEYS` |
| Frontmatter not valid YAML (unquoted values, Python-repr labels) | same |
| Local `.env` overrode the hub's `CENTRAL_CONFIG_PATH` | `dotenv_values` + priority env > central > `.env` |
| `.ai-context/` locked inside the install dir; tools returned repo-relative paths | `AI_CONTEXT_DIR`; absolute paths |
| Key regex took hostnames (`team-2.atlassian.net` → `TEAM-2`); no `_` keys | `extract_issue_key` |
| `server.py` exited / built the app at import; no instructions or annotations | `register_jira_tools`, `jira_instructions`, `create_server` |
| Pre-flight failure printed to stdout (breaks MCP stdio) | stderr |
| Tests made a real HTTP call (`_resolve_cloud_id`) | patched |
| CLI login rewrote `.env` wholesale (lost extra lines) | `set_key` per variable |
| Every log line printed twice on stderr under MCP (SDK root handler) | `propagate = False` |

## Open

| # | Priority | Where | Issue | Direction |
|---|---|---|---|---|
| B1 | High | `JiraClient.get_issue` (`expand=changelog`) | Jira embeds at most ~100 histories; older history is **silently dropped** from `history.md` | page `GET /rest/api/3/issue/{key}/changelog?startAt=` when `changelog.total > len(histories)` |
| B2 | High | `_format_history_markdown` | Description edits show only "Description updated.", so the requirement evolution (the main promise) is lost | render a unified diff (`difflib`) of `from`/`to` (the changelog has plain text for description) |
| B3 | Medium | `server.py` tools | Failures come back as normal text (`❌ …`), not `isError: true`, so hubs can't detect them | raise inside the tool (SDK turns it into `isError`) or return an error result; update AGENTS.md §4 |
| B4 | Medium | `core/indexer.py` | `catalog.json` read-modify-write has no lock and is not atomic; parallel syncs can lose entries or leave a torn file | write to a temp file + `os.replace`; `ponytail:` note for a lock if parallel use is real |
| B5 | Medium | `core/adf_parser.py` | Missing nodes: `panel`, `expand`/`nestedExpand`, `taskList`/`taskItem`, `status`, `emoji`, `date`, `mediaInline`, `decisionList`. Table cells don't escape `|` | add cases + one test each |
| B6 | Medium | `adf_parser` `media` + `sync_service` | Inline image link uses the raw `alt` (not sanitized like the saved file); non-image media links to a uuid; `.svg` is linked to `assets/` but never downloaded | share `_sanitize_filename`; map media id → attachment; decide on `image/svg+xml` |
| B7 | Medium | `download_attachment` | Uses the attachment `content` URL on the tenant domain; scoped tokens (gateway-only) may get 401 | when `api_url` is the gateway, use `{api_url}/rest/api/3/attachment/content/{id}` |
| B8 | Low | `sync_service` attachments | Two attachments with the same filename overwrite each other | suffix with attachment id on collision |
| B9 | Low | `JiraClient.__init__` | Network call (`tenant_info`) on every construction, i.e. every tool call | resolve lazily, or cache per base URL |
| B10 | Low | `server.py` packaging | Top-level module names `server`, `core`, `utils` collide with other Python children mounted in one hub process | move into a package (`jira_sync_ticket/`) when in-process mounting is actually used |
| B11 | Low | `jira_list_synced` | No filters; returns every ticket | add `status`/`label` filters only when an agent needs them (FEATURES.md first) |
| B12 | Low | catalog | Tickets deleted in Jira stay in the catalog forever | a "prune" action if it ever matters |
