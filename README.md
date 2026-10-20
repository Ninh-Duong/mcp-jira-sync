# mcp-jira-sync

Local MCP server and CLI that lets an AI agent read a Jira Cloud ticket before it works on it: description, screenshots, change history, related issues. The local copy is **encrypted**: only someone with the key and a working Jira login can read it, through the tools or the CLI. Read-only on Jira; runs standalone or as a child of an MCP hub (`/mcp-hub mcp-jira-sync PROJ-123 read this ticket first`).

## Quick start

Python 3.10+.

```bash
pip install -r requirements.txt
python utils/env_check.py
python cli.py                 # log in once (also creates the encryption key), then sync and read tickets
```

MCP client entry (details per client: [docs/AI_AGENT_SETUP.md](docs/AI_AGENT_SETUP.md)):

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

## Running under mcp-hub

With mcp-hub cloned as a sibling (`../mcp-hub` next to this repo), register the hub in your client instead of the entry above. Setup: `../mcp-hub/README.md`, section "Default setup".

- The hub launches `server.py` with its own interpreter (`../mcp-hub/.venv/Scripts/python.exe`, macOS/Linux `../mcp-hub/.venv/bin/python`), `cwd` this repo. Dependencies come from `uv sync` in `mcp-hub`, not `pip install` here.
- Credentials go in the `jira` block (`base_url`, `email`, `api_token`, `ai_context_key`, `max_asset_size_mb`) of `../mcp-hub/config/private/mcps/mcp-jira-sync.json`, passed as `CENTRAL_CONFIG_PATH`. `PYTHON_DOTENV_DISABLED=1` makes the server ignore this repo's `.env` entirely (including `AI_CONTEXT_DIR`), so `python cli.py` does not fix a hub setup. If the CLI and the hub share `.ai-context/`, `ai_context_key` must equal `JIRA_AI_CONTEXT_KEY` in `.env`.
- Tools are exposed as `jira__<tool>` (e.g. `jira__sync_ticket`). The hub does not forward `jira_instructions()`; agents get the hub contract `../mcp-hub/docs/mcps/mcp-jira-sync.md` instead.

## Documentation

- [docs/USAGE.md](docs/USAGE.md): CLI, MCP tools, output, debugging
- [docs/AI_AGENT_SETUP.md](docs/AI_AGENT_SETUP.md): connect an AI client
- [docs/JIRA_ACCESS.md](docs/JIRA_ACCESS.md): token, permissions, configuration
- [docs/AI_CONTEXT_FORMAT.md](docs/AI_CONTEXT_FORMAT.md): output format and encryption contract
- [docs/PARENT_MCP_GUIDE.md](docs/PARENT_MCP_GUIDE.md): MCP hub integration
- [docs/FEATURES.md](docs/FEATURES.md): what each feature does and does not do
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): modules and data flow
- [docs/STANDARDS.md](docs/STANDARDS.md), [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md), [docs/BACKLOG.md](docs/BACKLOG.md)

## Contributing (humans and AI agents)

Read [AGENTS.md](AGENTS.md) first. This repository is **public**: [docs/SECURITY.md](docs/SECURITY.md) is mandatory (no local paths, no real tenant, project, ticket, or people data, no secrets).
