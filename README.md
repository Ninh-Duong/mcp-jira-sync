# jira_sync_ticket

Local MCP server and CLI that turns a Jira Cloud ticket into Markdown + images an AI agent can read: description, screenshots, change history, related issues. Read-only on Jira; runs standalone or as a child of an MCP hub.

## Quick start

Python 3.10+.

```bash
pip install -r requirements.txt
python utils/env_check.py
python cli.py                 # log in once, then sync tickets from the menu
```

MCP client entry (details per client: [docs/AI_AGENT_SETUP.md](docs/AI_AGENT_SETUP.md)):

```json
{
  "mcpServers": {
    "jira-sync": {
      "command": "python",
      "args": ["<JIRA_SYNC_PATH>/server.py"],
      "env": { "AI_CONTEXT_DIR": "<WORKSPACE>/.ai-context" }
    }
  }
}
```

## Documentation

- [docs/USAGE.md](docs/USAGE.md): CLI, MCP tools, output, debugging
- [docs/AI_AGENT_SETUP.md](docs/AI_AGENT_SETUP.md): connect an AI client
- [docs/JIRA_ACCESS.md](docs/JIRA_ACCESS.md): token, permissions, configuration
- [docs/AI_CONTEXT_FORMAT.md](docs/AI_CONTEXT_FORMAT.md): output format contract
- [docs/PARENT_MCP_GUIDE.md](docs/PARENT_MCP_GUIDE.md): MCP hub integration
- [docs/FEATURES.md](docs/FEATURES.md): what each feature does and does not do
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): modules and data flow
- [docs/STANDARDS.md](docs/STANDARDS.md), [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md), [docs/BACKLOG.md](docs/BACKLOG.md)

## Contributing (humans and AI agents)

Read [AGENTS.md](AGENTS.md) first. This repository is **public**: [docs/SECURITY.md](docs/SECURITY.md) is mandatory (no local paths, no real tenant, project, ticket, or people data, no secrets).
