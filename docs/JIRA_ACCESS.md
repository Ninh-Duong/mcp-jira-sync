# Jira Access and Configuration

## 1. Create a token

Create an API token at https://id.atlassian.com/manage-profile/security/api-tokens.

- **Classic API token**: inherits your Atlassian user's permissions. Works on the tenant URL (`https://<domain>.atlassian.net`).
- **Scoped API token**: works only through the Atlassian gateway (`https://api.atlassian.com/ex/jira/<cloudId>`). The client finds the cloudId and switches automatically ([ARCHITECTURE.md §3](ARCHITECTURE.md#3-jira-access-strategy)). Grant the scopes in §2.

The token is used as Basic auth `email:token`. It never leaves this machine except to Atlassian.

## 2. Required permissions

Defined in [core/config.py](../core/config.py) (`REQUIRED_PERMISSIONS`, `JIRA_GRANULAR_SCOPES`) and shown by the CLI before login.

| Kind | Code | Needed for |
|---|---|---|
| Project permission | `BROWSE_PROJECTS` | viewing the issue, its attachments and changelog |
| Scope | `read:me` | `GET /rest/api/3/myself` (account check) |
| Scope | `read:jira-work` | classic scope covering issue reads |
| Scope | `read:issue-details:jira` | summary, description, fields, links |
| Scope | `read:attachment:jira` | downloading images |
| Scope | `read:issue.changelog:jira` | `history.md` (not `read:audit-log:jira`) |

The CLI checks `BROWSE_PROJECTS` globally with `/mypermissions`. A `false` there is a warning only: a single project can still grant access, and a real 403 shows up at sync time.

## 3. Configuration sources and priority

`load_config()` resolves **each value independently**, first match wins:

1. **Process environment**: what a hub or MCP client entry injects.
2. **Central JSON file** at `CENTRAL_CONFIG_PATH` (from env, or from `.env`).
3. **Local `.env`** in the repo root: written by the CLI login, read with `dotenv_values` (it never modifies `os.environ`).

Central file shape (the `jira` object is optional; a flat object also works):
```json
{ "jira": { "base_url": "https://your-domain.atlassian.net", "email": "you@example.com", "api_token": "…", "max_asset_size_mb": 15 } }
```
An unreadable central file is logged as a warning and skipped.

## 4. Variables

| Variable | Central key | Default | Meaning |
|---|---|---|---|
| `JIRA_BASE_URL` | `base_url` | none (required) | `https://<domain>.atlassian.net`; trailing `/` is stripped |
| `JIRA_EMAIL` | `email` | none (required) | Atlassian account email |
| `JIRA_API_TOKEN` | `api_token` | none (required) | classic or scoped API token |
| `MAX_ASSET_SIZE_MB` | `max_asset_size_mb` | `15` | per-image download cap; invalid → 15 |
| `CENTRAL_CONFIG_PATH` | n/a | unset | path to the central JSON (`~` expanded) |
| `AI_CONTEXT_DIR` | n/a | `<repo>/.ai-context` | output folder; env or `.env` only, read once at start |

`.env.example` lists them all. `save_config` (CLI login) updates only the four `JIRA_*` / `MAX_ASSET_SIZE_MB` lines and keeps everything else in `.env`.

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Jira API Error [401]` at login | wrong email/token, or a scoped token without `read:me`/`read:jira-work` | regenerate the token, check scopes |
| `[403] Access denied for ticket` | no Browse permission on that project | ask a Jira admin |
| `[404] Ticket … was not found` | typo, or the ticket is hidden from you (Jira returns 404 for both) | check the key in the browser |
| Images missing, `assets_count` lower than attachments | file over `MAX_ASSET_SIZE_MB`, or a download failed | see `logs/app.log`; raise the cap |
| Hub credentials ignored | the old code let `.env` win over the central file | fixed 2026-10-20: process env > central > `.env` |
