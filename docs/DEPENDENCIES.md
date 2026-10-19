# Dependencies

Three runtime packages, nothing else. Adding one needs a row here explaining why stdlib or these three can't do it.

## Runtime

| Package | Spec | Used for | Why it stays |
|---|---|---|---|
| `mcp` | `>=1.2.0` | MCP server over stdio (`server.py`) | Official SDK. The code supports **both** majors: 2.x `mcp.server.MCPServer` and 1.x `mcp.server.fastmcp.FastMCP` (fallback import in `create_server()`). Tests pass on both. |
| `httpx` | `>=0.27.0` | Jira REST calls, streaming attachment download with size cap | Timeouts, redirects, and streaming in a few lines. `urllib` would need hand-written streaming, redirect, and error handling. `mcp` already depends on it, so it costs nothing. |
| `python-dotenv` | `>=1.0.0` | `dotenv_values` (read `.env` without touching `os.environ`), `set_key` (update one line, keep the rest) | A correct `.env` parser and line-preserving writer; a hand-rolled one would mishandle quotes and comments. |

`utils/env_check.py` (`REQUIRED_PACKAGES`) must list exactly these.

## Dev / tooling

None installed by the project. Tests use stdlib `unittest` + `unittest.mock`. `uv` (optional) runs the suite on other Python or mcp versions without a venv.

## Deliberately excluded

| Package | Why not | Instead |
|---|---|---|
| `requests` / `aiohttp` | second HTTP stack | `httpx` |
| `pyyaml` / `ruamel` | only needed to *write* frontmatter | JSON scalars are valid YAML: `json.dumps` per value |
| ADF / Markdown libs (`adf2md`, `markdownify`) | large, lag behind ADF node types | `core/adf_parser.py`, ~150 lines of recursion |
| SQLite / Postgres / Chroma / Pinecone | the catalog is small and agents read files | `catalog.json` + `INDEX.md` |
| `pytest`, `responses`, `respx` | extra dev tree | `unittest` + `patch.object` on `JiraClient` |
| `click` / `typer` / `rich` / `questionary` | a 5-item menu | `input()` / `print()` in `cli.py` |
| `pydantic` (directly) | dataclasses suffice | `@dataclass` (`JiraConfig`, `SyncResult`) |
