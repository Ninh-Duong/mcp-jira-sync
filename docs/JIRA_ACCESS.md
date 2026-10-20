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
3. **Local `.env`** in the repo root: written by the CLI login, read with `dotenv_values` (it never modifies `os.environ`). Skipped entirely when `PYTHON_DOTENV_DISABLED` is `1`/`true`/`yes` (mcp-hub sets it), so a standalone `.env` never leaks into hub runs.

Central file shape (the `jira` object is optional; a flat object also works):
```json
{ "jira": { "base_url": "https://your-domain.atlassian.net", "email": "you@example.com", "api_token": "…", "ai_context_key": "…", "max_asset_size_mb": 15 } }
```
An unreadable central file is logged as a warning and skipped.

## 4. Variables

| Variable | Central key | Default | Meaning |
|---|---|---|---|
| `JIRA_BASE_URL` | `base_url` | none (required) | `https://<domain>.atlassian.net`; trailing `/` is stripped |
| `JIRA_EMAIL` | `email` | none (required) | Atlassian account email |
| `JIRA_API_TOKEN` | `api_token` | none (required) | classic or scoped API token |
| `JIRA_AI_CONTEXT_KEY` | `ai_context_key` | none (required to sync or read); the CLI login writes one to `.env` | Fernet key (32 url-safe base64 bytes) that encrypts `.ai-context/`. A secret like the token |
| `MAX_ASSET_SIZE_MB` | `max_asset_size_mb` | `15` | per-image download cap; invalid → 15 |
| `CENTRAL_CONFIG_PATH` | n/a | unset | path to the central JSON (`~` expanded) |
| `AI_CONTEXT_DIR` | n/a | `<repo>/.ai-context` | output folder; env or `.env` only, read once at start |
| `PYTHON_DOTENV_DISABLED` | n/a | unset | `1`/`true`/`yes`: ignore `.env` completely (set by mcp-hub) |

`.env.example` lists them all. `save_config` (CLI login) updates only the `JIRA_BASE_URL` / `JIRA_EMAIL` / `JIRA_API_TOKEN` / `MAX_ASSET_SIZE_MB` lines and keeps everything else in `.env`. It adds `JIRA_AI_CONTEXT_KEY` only when no source has one, and never replaces an existing key.

### The encryption key

- **Reading needs two things**: the key, and a Jira login that works at that moment (the tools call `/myself` first). A copy of `.ai-context/` alone, or the key alone with a revoked token, reads nothing. See [FEATURES.md F7](FEATURES.md#f7-encrypted-ai-context-and-the-access-gate).
- **Sharing**: teammates who should read the same `.ai-context/` need the same key. Send it the way you would send a token (password manager), never in a repo, ticket, or chat with an agent. Each of them still logs in with their own Jira token.
- **Hub**: the server never writes the key. Put `ai_context_key` in the hub's central JSON next to `api_token`, or inject `JIRA_AI_CONTEXT_KEY`.
- **Lost or changed key**: old files cannot be decrypted. Delete `.ai-context/` and sync the tickets again.
- Make one by hand: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Jira API Error [401]` at login | wrong email/token, or a scoped token without `read:me`/`read:jira-work` | regenerate the token, check scopes |
| `[403] Access denied for ticket` | no Browse permission on that project | ask a Jira admin |
| `[404] Ticket … was not found` | typo, or the ticket is hidden from you (Jira returns 404 for both) | check the key in the browser |
| Images missing, `assets_count` lower than attachments | file over `MAX_ASSET_SIZE_MB`, or a download failed | see `logs/app.log`; raise the cap |
| Hub credentials ignored | the old code let `.env` win over the central file | fixed 2026-10-20: process env > central > `.env` |
| `No access: JIRA_AI_CONTEXT_KEY is not set` | no key in any source (always the case under a hub until you add one) | run `python cli.py` once, or add `ai_context_key` to the central JSON |
| `No access: cannot log in to Jira …` | token expired/revoked, or no network | `python cli.py` → `[3]` to log in again |
| `No access: cannot decrypt …` | the key is not the one the files were written with, or a file was edited | use the original key, or delete `.ai-context/` and re-sync |
