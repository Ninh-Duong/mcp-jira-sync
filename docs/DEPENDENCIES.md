# Dependencies

Four runtime packages, nothing else. Adding one needs a row here explaining why stdlib or these four can't do it.

## Runtime

| Package | Spec | Used for | Why it stays |
|---|---|---|---|
| `mcp` | `>=1.2.0` | MCP server over stdio (`server.py`) | Official SDK. The code supports **both** majors: 2.x `mcp.server.MCPServer` and 1.x `mcp.server.fastmcp.FastMCP` (fallback import in `create_server()`). Tests pass on both. |
| `httpx` | `>=0.27.0` | Jira REST calls, streaming attachment download with size cap | Timeouts, redirects, and streaming in a few lines. `urllib` would need hand-written streaming, redirect, and error handling. `mcp` already depends on it, so it costs nothing. |
| `python-dotenv` | `>=1.0.0` | `dotenv_values` (read `.env` without touching `os.environ`), `set_key` (update one line, keep the rest) | A correct `.env` parser and line-preserving writer; a hand-rolled one would mishandle quotes and comments. |
| `cryptography` | `>=42.0.0` | `Fernet` in `core/vault.py`: authenticated encryption of everything under `.ai-context/` | Python's stdlib has no block cipher, and hand-written crypto is never acceptable. Fernet is one call each way, misuse-resistant (random IV, HMAC, versioned token), and the de-facto standard package (prebuilt wheels on every platform). Also pulled in by many MCP/HTTP stacks already. |

`utils/env_check.py` (`REQUIRED_PACKAGES`) must list exactly these.

## Dev / tooling

No dev packages are installed by the project. Tests use stdlib `unittest` + `unittest.mock`. Standalone setup and CI use `uv sync --locked` and `uv run --locked` with the committed `uv.lock`, which resolves Python 3.10+ and platform-specific dependencies. Update dependency versions deliberately with `uv lock --upgrade`, then rerun the development checks. `requirements.txt` keeps the same four compatible ranges for pip users; it is not an exact lockfile. The Hub continues to supply its own environment and dependency lock.

Setuptools builds only `core`, `utils`, `server`, and `cli`, avoiding accidental discovery of local data directories. CI syncs the project and runs the pre-flight, unit tests, and compilation checks on Windows/macOS/Ubuntu with Python 3.10/3.12.

## Deliberately excluded

| Package | Why not | Instead |
|---|---|---|
| `requests` / `aiohttp` | second HTTP stack | `httpx` |
| `pyyaml` / `ruamel` | only needed to *write* frontmatter | JSON scalars are valid YAML: `json.dumps` per value |
| ADF / Markdown libs (`adf2md`, `markdownify`) | large, lag behind ADF node types | `core/adf_parser.py`, ~150 lines of recursion |
| SQLite / Postgres / Chroma / Pinecone | the catalog is small | encrypted `catalog.json.enc` |
| `pycryptodome` / `PyNaCl` / AES-GCM with a custom file header | more API surface for the same result | `cryptography.fernet` (ticket files are small: no streaming or framing needed) |
| `pytest`, `responses`, `respx` | extra dev tree | `unittest` + `patch.object` on `JiraClient` |
| `click` / `typer` / `rich` / `questionary` | a 6-item menu | `input()` / `print()` in `cli.py` |
| `pydantic` (directly) | dataclasses suffice | `@dataclass` (`JiraConfig`, `SyncResult`) |
