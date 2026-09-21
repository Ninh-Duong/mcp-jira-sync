# 🛡️ Architectural Rules & Guidelines for AI Agents (`rules.md`)

This repository is built with a strictly modular architecture designed for local MCP tool execution and multi-agent discovery. Any AI Agent modifying, refactoring, or extending this codebase **MUST** strictly adhere to the following non-negotiable rules.

---

## 1. Separation of Concerns & Modular Design

- **NO Monoliths**: Never merge `core/`, `utils/`, `cli.py`, or `server.py` into a single script. Each layer has a distinct responsibility:
  - `core/`: Pure business logic (Jira REST client, ADF parser, sync pipeline, index manager). It must remain decoupled from CLI prompts and MCP protocol decorators.
  - `utils/`: Independent utilities (`logger.py`, `env_check.py`).
  - `cli.py`: Interactive user terminal interface only.
  - `server.py`: Model Context Protocol (MCP) server endpoints only.
- When adding a new feature:
  - Put data retrieval or transformation logic in `core/`.
  - Expose a user action in `cli.py`.
  - Wrap and expose the tool in `server.py`.

---

## 2. 100% Relative & Portable Paths (Zero Hardcoding)

- **NEVER** hardcode absolute paths (e.g., `C:\...`, `D:\...`, `/home/...`).
- Always compute paths dynamically from the project root using `pathlib.Path`:
  ```python
  from pathlib import Path
  BASE_DIR = Path(__file__).resolve().parent.parent # or project root
  ```
- All output files must resolve into:
  - `logs/` for runtime diagnostic logs.
  - `.ai-context/` for synchronized ticket data and indexes.
  - `.env` for local configuration.
- The project must run identically across Windows, Linux, and macOS.

---

## 3. MCP Stdio Protocol Protection (CRITICAL)

- `server.py` communicates with AI clients (Claude, Cursor, Antigravity) over standard I/O (`stdio`) via JSON-RPC.
- **NEVER** use `print()` in `server.py` or any module imported during MCP server runtime that outputs to `sys.stdout`.
- Any unexpected output to `sys.stdout` will corrupt the JSON-RPC message framing and crash the MCP connection.
- All diagnostics and logs must be sent to `sys.stderr` or written to `logs/app.log`.

---

## 4. Structured Logging for AI Debugging

- Every function in `core/` and entrypoints must log significant steps (`DEBUG`, `INFO`, `WARNING`, `ERROR`).
- **All exceptions must be logged with full stack trace**:
  ```python
  logger.error(f"Failed to sync {key}: {e}", exc_info=True)
  ```
- Do not alter the log format in `utils/logger.py`:
  `%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d in %(funcName)s] %(message)s`
  This enables AI Agents to parse `logs/app.log`, pinpoint exact line numbers, and self-heal code without human debugging.

---

## 5. Security & Git Integrity

- Never commit credentials, API tokens, internal issue descriptions, or diagnostic logs.
- The following paths **MUST ALWAYS** remain in `.gitignore`:
  - `.env` and `*.env`
  - `logs/` and `*.log`
  - `.ai-context/`
  - `.venv/` and `__pycache__/`
- Never log raw API tokens in cleartext in console or `logs/app.log`.

---

## 6. Data Storage & Multi-Agent Compatibility

- Synced ticket structure under `.ai-context/` must strictly follow:
  ```
  .ai-context/
  ├── INDEX.md                     # Markdown summary table of all tickets
  ├── catalog.json                 # JSON metadata dictionary for machine filtering
  └── tickets/
      └── <KEY>/
          ├── ticket.md            # Mandatory YAML frontmatter + markdown body
          ├── history.md           # Chronological changelog timeline
          └── assets/              # Local image files linked from ticket.md
  ```
- **`ticket.md` must start with YAML frontmatter** containing: `key`, `summary`, `status`, `type`, `priority`, `assignee`, `reporter`, `created`, `updated`, `url`, `labels`, `assets_count`.
- Any sync operation **MUST** trigger `indexer.register_ticket()` to update both `INDEX.md` and `catalog.json`.

---

## 7. Dependency & Simplicity (Ponytail Principle)

- Keep dependencies minimal: `mcp`, `httpx`, `python-dotenv`.
- Do NOT add database drivers (SQLite, PostgreSQL, Chroma, Pinecone) or external ADF parsing libraries when standard file I/O and standard Python recursion already solve the problem.
- Always run pre-flight check and tests after making any code modifications:
  ```bash
  python utils/env_check.py
  python -m unittest discover tests
  ```
