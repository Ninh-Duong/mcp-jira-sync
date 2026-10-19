# `.ai-context/` Output Format (contract)

Agents in other repositories read these files directly, so this layout is a **public contract**. Changing it is a breaking change: update this file, its changelog (§7), and `TestContracts` in `tests/test_sync.py` in the same change.

Writers: `SyncService.sync` ([core/sync_service.py](../core/sync_service.py)) and `register_ticket` ([core/indexer.py](../core/indexer.py)).

---

## 1. Location

`AI_CONTEXT_DIR`, resolved once at import in [core/config.py](../core/config.py):

1. process env `AI_CONTEXT_DIR`, else
2. `AI_CONTEXT_DIR` in this repo's `.env`, else
3. `<repo>/.ai-context`.

`~` is expanded and the path is made absolute. Tools always return absolute POSIX paths (forward slashes, also on Windows). Put it inside the agent's workspace (e.g. `<WORKSPACE>/.ai-context`) when the agent's file tools are limited to that workspace, and add it to that repo's `.gitignore` (ticket data is internal).

## 2. Tree

```
<AI_CONTEXT_DIR>/
├── INDEX.md                  # human/agent table of every synced ticket
├── catalog.json              # machine-readable catalog (source of INDEX.md)
└── tickets/
    └── <KEY>/                # KEY = upper-case issue key, e.g. PROJ-123
        ├── ticket.md         # frontmatter + description + assets + relations
        ├── history.md        # changelog, newest first
        └── assets/           # downloaded images only; absent when there are none
            └── <filename>
```

## 3. `ticket.md`

### 3.1 Frontmatter

Starts at line 1 with `---`. Every value is a **JSON scalar or array**, which is also valid YAML: strings in double quotes with JSON escapes, `labels` as a flow list, and `assets_count` as an integer. A parser can use `yaml.safe_load` or `json.loads` per value.

Keys, in this exact order (`FRONTMATTER_KEYS`):

| Key | Type | Source (Jira `fields`) | Fallback |
|---|---|---|---|
| `key` | string | normalized input key | n/a |
| `summary` | string | `summary` | `"No Summary Provided"` |
| `status` | string | `status.name` | `"N/A"` |
| `type` | string | `issuetype.name` | `"Issue"` |
| `priority` | string | `priority.name` | `"N/A"` |
| `assignee` | string | `assignee.displayName` | `"Unassigned"` |
| `reporter` | string | `reporter.displayName` | `"Unknown"` |
| `created` | string | `created` (Jira ISO with offset, e.g. `2026-09-29T12:12:46.422+1000`) | `""` |
| `updated` | string | `updated` | `""` |
| `url` | string | `<JIRA_BASE_URL>/browse/<KEY>` | n/a |
| `labels` | string[] | `labels` | `[]` |
| `assets_count` | int | images actually downloaded | `0` |

Example:
```yaml
---
key: "PROJ-123"
summary: "Fix \"login\" crash: token expiry"
status: "In Progress"
type: "Bug"
priority: "High"
assignee: "Alex Taylor"
reporter: "Sam Morgan"
created: "2026-09-29T12:12:46.422+1000"
updated: "2026-10-19T19:43:58.277+1100"
url: "https://your-domain.atlassian.net/browse/PROJ-123"
labels: ["mobile", "auth"]
assets_count: 1
---
```

### 3.2 Body (section order is fixed)

1. `# [<KEY>] <summary>`, then a blockquote with Source link, Type / Status / Priority, Assignee / Reporter, Last Updated, and a link to `history.md`.
2. `## 1. Description & Requirements`: the description converted from ADF ([core/adf_parser.py](../core/adf_parser.py)); `*No description provided.*` when empty.
3. `## 2. Visual Assets & Screenshots`: one `### 📷 <filename>` + `![<filename>](assets/<filename>)` per downloaded image, or `*No image attachments found.*`.
4. `## 3. Other Attachments & Documents`: **only when present**. Non-image attachments as links to their Jira URL (need a Jira login) with size in KB. They are not downloaded.
5. `## 4. Related Issues & Dependencies`: parent, subtasks (with status), issue links (inward/outward wording from Jira), or `*No related dependencies recorded.*`.

Images embedded in the description (`media` nodes whose `alt` ends in an image extension) also link to `assets/<alt>`.

## 4. `history.md`

```
# 📜 Change History (Changelog): [<KEY>] <summary>

> Chronological order: Newest to oldest. ...

### ⏱️ <created> — Updated by: **<author displayName>**
- **<field>**: `<fromString>` ➔ `<toString>`
- **description**: Description updated.
```

- Source: `changelog.histories` from `GET /issue/{key}?expand=changelog` (Jira returns at most about 100 entries this way; see [BACKLOG.md](BACKLOG.md)).
- Sorted by `created`, newest first. Empty values render as `(empty)`.
- Description edits (field `description` or `mô tả`) show only `Description updated.`, with no diff.
- No histories: `*No changelog entries recorded.*`

## 5. `catalog.json` and `INDEX.md`

```json
{
  "updated_at": "<UTC ISO>",
  "total_tickets": 2,
  "tickets": {
    "<KEY>": {
      "key": "<KEY>", "summary": "...", "type": "...", "status": "...", "priority": "...",
      "assignee": "...", "jira_updated_at": "<fields.updated>", "synced_at": "<UTC ISO>",
      "assets_count": 0, "history_count": 3,
      "ticket_path": "tickets/<KEY>/ticket.md", "history_path": "tickets/<KEY>/history.md",
      "labels": []
    }
  }
}
```

- Paths inside the catalog are **relative to `AI_CONTEXT_DIR`**, so the folder can be moved. Tools turn them into absolute paths.
- Every successful sync calls `register_ticket()`. It upserts the entry and regenerates `INDEX.md` (a table sorted by `jira_updated_at` desc, plus reading guidelines).
- An unreadable `catalog.json` is logged and rebuilt empty. Entries are never removed by a sync.

## 6. Asset rules

- Downloaded MIME types: `image/png`, `image/jpeg`, `image/jpg`, `image/webp`, `image/gif` (`IMAGE_MIME_TYPES`).
- Size cap: `MAX_ASSET_SIZE_MB` (default 15), checked against `Content-Length` and while streaming. Oversized or failed downloads are skipped, logged, and left out of `assets_count`.
- Filenames: `\ / * ? : " < > |` are replaced with `_`.
- **Purge on re-sync**: a file in `assets/` whose name is not an image attachment of the ticket any more is deleted, and an empty `assets/` folder is removed. `ticket.md` and `history.md` are overwritten on every sync. Never hand-edit anything under `.ai-context/`.

## 7. Format changelog

| Date | Change |
|---|---|
| 2026-10-20 | Frontmatter values are JSON-quoted (valid YAML). Before, `key`/`status`/... were unquoted and `labels` was a Python repr (`['a', 'b']`). |
| 2026-10-20 | `AI_CONTEXT_DIR` can move the folder; tools return absolute paths (were relative to the repo). |
