# Coding Standards

## 1. Language and runtime
- **Python ≥ 3.10** (`requires-python` in `pyproject.toml`, checked by `utils/env_check.py`). Don't use syntax from newer versions: no reused outer quote or backslash inside f-string `{}` (3.12), no `except*` or `typing.Self` (3.11).
- Typing from `typing` (`Optional`, `Dict`, `List`, `Any`), matching the existing code. Annotate public functions.
- Data carriers are `@dataclass` (`JiraConfig`, `SyncResult`); don't add pydantic models outside MCP types.

## 2. Code organization
- One responsibility per module; see the code map in [AGENTS.md](../AGENTS.md#code-map). Pure transforms (`adf_parser`, `_format_*_markdown`, `extract_issue_key`) stay free of I/O so they can be tested directly.
- Short functions. Name a new step after what it does instead of growing `SyncService.sync`.
- No dead code: remove unused functions or files in the change that makes them unused.
- Comments say **why** (limits, Jira quirks, security). Mark a deliberate shortcut with a `ponytail:` comment naming its ceiling and the upgrade path.
- Constants that form a contract live next to their writer, are documented, and are tested: `FRONTMATTER_KEYS`, `IMAGE_MIME_TYPES`, `REQUIRED_PERMISSIONS`, `JIRA_GRANULAR_SCOPES`.

## 3. MCP tools
- A tool is a plain function in `server.py` with a docstring (the docstring is the tool description agents see) and **one** `app.add_tool(fn, name=f"{prefix}...", annotations=ToolAnnotations(...))` line in `register_jira_tools`. No `@app.tool()` decorators: they bind to one app and block mounting.
- Annotations: `readOnlyHint=True` unless the tool writes files (only `jira_sync_ticket`, with `destructiveHint=False`); `openWorldHint=True` when it calls Jira, which includes every tool behind the access gate.
- Arguments: simple JSON types with defaults; accept the forms a human would paste (key or URL).
- Return text an agent can act on: the content itself (decrypted only behind the gate), the next step, and where the logs are. Keep `jira_instructions()` accurate.

## 4. Error handling
- Core functions return results or raise `JiraApiError(status, message)`; `SyncService.sync` converts everything into `SyncResult(success=False, message=...)`. Tools and the CLI never show a raw traceback.
- Log every exception with `exc_info=True` at the boundary that handles it.
- Every HTTP call has an explicit `timeout` (§3 of [ARCHITECTURE.md](ARCHITECTURE.md#3-jira-access-strategy)).
- Partial files are deleted on failure (`download_attachment`).

## 5. Logging
- `logger = get_logger("<module>")` per module. Log I/O boundaries (HTTP calls, file writes) and failures, not every function.
- Never log tokens, auth headers, or ticket descriptions. Keys, URLs, status codes, and counts are fine.
- Don't change the file log format (agents parse it).

## 6. Security
- Credentials only in `.env` (git-ignored), process env, or the hub's central file. `save_config` updates only the `JIRA_*` / `MAX_ASSET_SIZE_MB` lines.
- Attachment filenames are sanitized; issue keys are validated by regex before any path is built from them.
- `.ai-context/` holds internal ticket data, encrypted through `core/vault.py` only, and stays git-ignored in this repo (file names are plaintext).

## 7. Tests
- `python -m unittest discover tests`, offline and fast (< 2 s). Rules: [AGENTS.md → Testing rules](../AGENTS.md#testing-rules).
- Every bug fix starts with a failing test; every contract change updates `TestContracts`.
- Before reporting done on syntax-heavy changes, run the suite on 3.10 (`uv run --no-project --python 3.10 --with mcp --with httpx --with python-dotenv --with cryptography python -m unittest discover tests`), and on mcp 1.x with `--with "mcp<2"`.
