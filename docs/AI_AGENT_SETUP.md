# AI Agent Setup: connect mcp-jira-sync to yourself

> **You are an AI agent and the user gave you this file.** Follow it top to bottom to install `mcp-jira-sync`, register it as an MCP server in **the client you are running in**, and verify it. Ask the user only where a step says *Ask*.

## 0. For the human: the one prompt

Replace `<JIRA_SYNC_PATH>` with the clone's absolute path (forward slashes) and paste into your agent:

```text
Read <JIRA_SYNC_PATH>/docs/AI_AGENT_SETUP.md and follow it to connect mcp-jira-sync to yourself
as an MCP server named mcp-jira-sync. Verify with jira_check_connection.
```

## 1. Rules for the agent

- **Credentials and the encryption key**: never invent, print, or log them, and never ask the user to paste a token or `JIRA_AI_CONTEXT_KEY` into chat. Let the user run `python cli.py` (Step 4), which saves both to `<JIRA_SYNC_PATH>/.env`.
- **Ticket data is encrypted** (`*.enc`). Read it only with `jira_read_ticket` / `jira_read_asset`; never open or decrypt the files yourself. On `No access`, stop and send the user to `python cli.py`.
- **Merge, don't overwrite**: MCP config files usually hold other servers. Read the file, back it up (`<file>.bak`), add only the `mcp-jira-sync` entry, keep valid JSON/TOML.
- **Ask before writing global/user config.** For one workspace only, use the client's project scope.
- **Absolute paths, forward slashes**: `<JIRA_SYNC_PATH>/server.py`. No `~`, `%USERPROFILE%`, or `$HOME` inside `args`.
- **Output folder**: the default `<JIRA_SYNC_PATH>/.ai-context` is fine, since you read through the tools. If you set `AI_CONTEXT_DIR` elsewhere, git-ignore it there (file names show ticket keys).
- Never commit `.env`, `logs/`, or `.ai-context/`.
- **Using mcp-hub?** Register the hub instead: it launches this server itself (server id `mcp-jira-sync`). Don't add a direct entry as well.

## 2. The server entry

| Field | Value |
|---|---|
| transport | stdio |
| command | `python` (or the absolute interpreter path, see Step 2) |
| args | `["<JIRA_SYNC_PATH>/server.py"]` |
| env | optional: `AI_CONTEXT_DIR`, `JIRA_BASE_URL` / `JIRA_EMAIL` / `JIRA_API_TOKEN` / `JIRA_AI_CONTEXT_KEY`, `CENTRAL_CONFIG_PATH` ([JIRA_ACCESS.md §4](JIRA_ACCESS.md#4-variables)) |

```json
{
  "mcpServers": {
    "mcp-jira-sync": {
      "command": "python",
      "args": ["<JIRA_SYNC_PATH>/server.py"]
    }
  }
}
```

## 3. Steps

**Step 1: Find the clone.** Use the path the user gave, or a folder with `server.py` + `AGENTS.md` + `core/sync_service.py`. Record `<JIRA_SYNC_PATH>`. *Ask* if unsure. **Done when** `<JIRA_SYNC_PATH>/server.py` exists.

**Step 2: Python 3.10+ and dependencies.**
```bash
python --version
python -m pip install -r "<JIRA_SYNC_PATH>/requirements.txt"
python "<JIRA_SYNC_PATH>/utils/env_check.py"
```
Record the absolute interpreter (`where python` / `which python`). GUI clients may not see a venv/pyenv Python on your shell PATH; use the absolute path as `command` if spawning fails. **Done when** env_check prints `[SUCCESS]`.

**Step 3: Register** the entry (§2) in your client (§4). **Done when** the config file contains `mcp-jira-sync` and still parses.

**Step 4: Credentials.** If `<JIRA_SYNC_PATH>/.env` has no real `JIRA_API_TOKEN` or no `JIRA_AI_CONTEXT_KEY` (check that the lines exist; never print their values), *ask* the user to run `python cli.py` in `<JIRA_SYNC_PATH>` and log in (token: https://id.atlassian.com/manage-profile/security/api-tokens). **Done when** the user confirms the login.

**Step 5: Reload and verify.** Reload the client, then call `jira_check_connection`. **Done when** it returns `✅ Jira Cloud connection active!`. Optionally sync a ticket the user names with `jira_sync_ticket`, then read it with `jira_read_ticket`.

## 4. Client reference

| Client | Where |
|---|---|
| Claude Code | `claude mcp add --transport stdio --scope user mcp-jira-sync -- python "<JIRA_SYNC_PATH>/server.py"` (`--scope project` writes `.mcp.json`). Verify: `claude mcp list` or `/mcp`. |
| Claude Desktop | Windows `%APPDATA%\Claude\claude_desktop_config.json`, macOS `~/Library/Application Support/Claude/claude_desktop_config.json`; §2 shape. Quit fully and reopen. |
| Cursor | global `~/.cursor/mcp.json`, project `.cursor/mcp.json`; §2 shape. |
| VS Code + Copilot | `.vscode/mcp.json` with key `"servers"` and `"type": "stdio"` per entry; or **MCP: Open User Configuration**. |
| Google Antigravity | global `~/.gemini/config/mcp_config.json` (older builds: `~/.gemini/antigravity/mcp_config.json`), workspace `.agents/mcp_config.json`; §2 shape. |
| OpenAI Codex | `codex mcp add mcp-jira-sync -- python "<JIRA_SYNC_PATH>/server.py"`, or `[mcp_servers.mcp-jira-sync]` in `~/.codex/config.toml` (single-quoted TOML strings for Windows paths). |
| Other | map §2 onto the client's stdio server config: watch the top-level key (`mcpServers`, `servers`, `mcp`), whether `type` is required, and whether command and args are one array. |

Client config paths change; if a path doesn't exist, check the client's current MCP docs and keep the §2 entry.

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| Server fails to start / no tools | Run `python "<JIRA_SYNC_PATH>/server.py"` in a terminal: a missing dependency prints the reason on stderr. Use the absolute python path. |
| `not configured yet` | Step 4. |
| `No access: …` | Step 4 (missing key, or the login stopped working); details in [JIRA_ACCESS.md §5](JIRA_ACCESS.md#5-troubleshooting). |
| Sync failed | Read `<JIRA_SYNC_PATH>/logs/app.log` (last ERROR has file:line and traceback); see [JIRA_ACCESS.md §5](JIRA_ACCESS.md#5-troubleshooting). |
