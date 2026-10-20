# Parent MCP / Hub Integration Guide

How a hub (master/router MCP) consumes `mcp-jira-sync` as a child feature. The patterns (subprocess, in-process mount with a prefix, server instructions) are the usual ones for MCP hubs, so other children can follow the same contract.

| Pattern | Use when | Isolation | Prefixing |
|---|---|---|---|
| 1. Subprocess stdio | the hub is in any language (Node, Go, Python), or you want crash isolation | full | the hub renames when it re-exposes tools |
| 2. In-process Python | the hub is a Python `MCPServer` / `FastMCP` and you want zero IPC | none | `register_jira_tools(app, prefix)` |
| 3. Programmatic | the hub wants the data, not the MCP envelope | none | n/a |

Tool names already carry a `jira_` namespace, so the default prefix is `""`. Add one only on a name clash.

---

## Pattern 1: subprocess over stdio (recommended)

The child is launched as `python <JIRA_SYNC_PATH>/server.py`. Inject configuration as environment variables; they win over the child's own `.env` ([JIRA_ACCESS.md §3](JIRA_ACCESS.md#3-configuration-sources-and-priority)).

| Env | Purpose |
|---|---|
| `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_AI_CONTEXT_KEY` | credentials and the encryption key, or instead… |
| `CENTRAL_CONFIG_PATH` | …a hub-wide secrets JSON with a `jira` object (`ai_context_key` next to `api_token`) |
| `AI_CONTEXT_DIR` | where the encrypted tickets are written (default `<JIRA_SYNC_PATH>/.ai-context`; agents read through the tools, so it need not be in their workspace) |
| `MAX_ASSET_SIZE_MB` | optional image cap |
| `PYTHON_DOTENV_DISABLED` | `1` to ignore the child's own `.env` (recommended for hubs) |

Node / TypeScript hub:
```typescript
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const transport = new StdioClientTransport({
  command: 'python',                                   // or the absolute python path
  args: ['<JIRA_SYNC_PATH>/server.py'],
  env: {
    ...process.env,
    CENTRAL_CONFIG_PATH: '<HUB_SECRETS_JSON>',   // {"jira": {"base_url": …, "email": …, "api_token": …, "ai_context_key": …}}
    PYTHON_DOTENV_DISABLED: '1',
  },
});
const jira = new Client({ name: 'hub', version: '1.0.0' });
await jira.connect(transport);

const { tools } = await jira.listTools();   // jira_sync_ticket, jira_read_ticket, jira_read_asset, jira_list_synced, jira_check_connection
const instructions = jira.getInstructions();           // forward into the hub's own instructions
await jira.callTool({ name: 'jira_sync_ticket', arguments: { issue_key: 'PROJ-123' } });
const ticket = await jira.callTool({ name: 'jira_read_ticket', arguments: { issue_key: 'PROJ-123' } });
```

Python hub (mcp SDK client):
```python
import os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(
    command=sys.executable,
    args=["<JIRA_SYNC_PATH>/server.py"],
    env={**os.environ, "CENTRAL_CONFIG_PATH": "<HUB_SECRETS_JSON>"},   # pass os.environ: the SDK default env is minimal
)
async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
    init = await session.initialize()          # init.instructions = jira_instructions()
    await session.call_tool("jira_sync_ticket", {"issue_key": "PROJ-123"})
    ticket = await session.call_tool("jira_read_ticket", {"issue_key": "PROJ-123"})
```

Notes:
- The child's stderr carries its logs; its `logs/app.log` stays in the child's folder.
- Run `python <JIRA_SYNC_PATH>/utils/env_check.py` once at hub install time; on a missing dependency the child exits 1 with the reason on stderr.
- Credentials and the key can't be entered through MCP. If `jira_check_connection` reports "not configured", or a read returns `No access: JIRA_AI_CONTEXT_KEY is not set`, the hub must provide env / the central file, or the user runs `python cli.py` in the child folder. The child never writes a key itself, so with `PYTHON_DOTENV_DISABLED=1` the hub **must** supply it.
- Read-only hubs: `jira_sync_ticket` is the only tool with `readOnlyHint: false`. A user asking to "read PROJ-123" is asking for that write; the three read tools and `jira_check_connection` are read-only.
- `jira_read_asset` returns an MCP **image** block; a hub that re-exposes results must pass non-text content through.

---

## Pattern 2: in-process mount (Python hub)

```python
import os, sys
os.environ.setdefault("CENTRAL_CONFIG_PATH", "<HUB_SECRETS_JSON>")   # credentials + ai_context_key
sys.path.insert(0, "<JIRA_SYNC_PATH>")

from mcp.server import MCPServer          # mcp 1.x: from mcp.server.fastmcp import FastMCP
from server import register_jira_tools, jira_instructions

hub = MCPServer(
    "my-hub",
    instructions="My hub tools …\n\n" + jira_instructions(),          # same prefix as below
)
register_jira_tools(hub)                  # or register_jira_tools(hub, prefix="x_") + jira_instructions("x_")
# register other children …
hub.run(transport="stdio")
```

- Importing `server` does not exit, prompt, or start anything (it only sets up the `jira_sync` logger).
- Server instructions are fixed when the hub creates its server, so append `jira_instructions(prefix)` yourself.
- **Limit**: the child uses top-level module names `server`, `core`, `utils`. Two children with the same names can't share one process; use Pattern 1 for them (packaging under a unique name is in [BACKLOG.md](BACKLOG.md)).

---

## Pattern 3: programmatic

```python
from core.config import JiraConfig
from core.sync_service import SyncService, read_synced_file
from core.vault import unlock

config = JiraConfig(base_url=..., email=..., api_token=..., ai_context_key=...)
result = SyncService(config).sync("PROJ-123")
if result.success:
    ticket_md = read_synced_file("PROJ-123", "ticket.md", unlock(config)).decode("utf-8")  # NoAccessError if gated out
else:
    print(result.message)       # never raises
```

`SyncService()` without arguments uses `load_config()`. Output layout and encryption: [AI_CONTEXT_FORMAT.md](AI_CONTEXT_FORMAT.md).
