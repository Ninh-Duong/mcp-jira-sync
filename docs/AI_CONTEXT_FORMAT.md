# `.ai-context/` Output Format (contract)

Every file here is **encrypted**. Agents read the content through `jira_read_ticket` / `jira_read_asset` (never by opening the files), and those tools return the plaintext described below. The plaintext layout and the on-disk layout are a **public contract**: changing either is a breaking change. Update this file, its changelog (§7), and `TestContracts` in `tests/test_sync.py` in the same change.

Writers: `SyncService.sync` ([core/sync_service.py](../core/sync_service.py)) and `register_ticket` ([core/indexer.py](../core/indexer.py)), both through [core/vault.py](../core/vault.py).

---

## 1. Location

`AI_CONTEXT_DIR`, resolved once at import in [core/config.py](../core/config.py):

1. process env `AI_CONTEXT_DIR`, else
2. `AI_CONTEXT_DIR` in this repo's `.env`, else
3. `<repo>/.ai-context`.

`~` is expanded and the path is made absolute. Agents no longer need the folder inside their workspace, since they read through the tools. The contents are encrypted, but folder and file names (ticket keys, image names) are not, so keep it in `.gitignore` unless those names may be public.

## 2. Tree and encryption

```
<AI_CONTEXT_DIR>/
├── catalog.json.enc              # catalog of every synced ticket (§5)
└── tickets/
    └── <KEY>/                    # KEY = upper-case issue key, e.g. PROJ-123
        ├── ticket.md.enc         # frontmatter + description + assets + relations (§3)
        ├── history.md.enc        # changelog, newest first (§4)
        └── assets/               # downloaded images only; absent when there are none
            └── <filename>.enc
```

- **File format**: each `.enc` file is one [Fernet token](https://github.com/fernet/spec/blob/master/Spec.md) (`cryptography.fernet`: AES-128-CBC with a random IV, plus HMAC-SHA256 over version, timestamp, IV, and ciphertext), stored as its url-safe base64 text. The plaintext is the UTF-8 Markdown/JSON below, or the raw image bytes.
- **Key**: `JIRA_AI_CONTEXT_KEY`, a 32-byte url-safe base64 Fernet key ([JIRA_ACCESS.md](JIRA_ACCESS.md#the-encryption-key)). One key per `.ai-context/`.
- **Reading**: only after the access gate (key set **and** a working Jira login), see [FEATURES.md F7](FEATURES.md#f7-encrypted-ai-context-and-the-access-gate). A wrong key or an edited file fails the HMAC and gives `No access: cannot decrypt ...`.
- Only [core/vault.py](../core/vault.py) encrypts or decrypts. Never write a plaintext file here.

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

## 5. `catalog.json.enc`

```json
{
  "updated_at": "<UTC ISO>",
  "total_tickets": 2,
  "tickets": {
    "<KEY>": {
      "key": "<KEY>", "summary": "...", "type": "...", "status": "...", "priority": "...",
      "assignee": "...", "jira_updated_at": "<fields.updated>", "synced_at": "<UTC ISO>",
      "assets_count": 0, "history_count": 3,
      "ticket_path": "tickets/<KEY>/ticket.md.enc", "history_path": "tickets/<KEY>/history.md.enc",
      "labels": [],
      "assets": { "<image file name>": { "id": "<Jira attachment id>", "size": 1234 } }
    }
  }
}
```

- Paths inside the catalog are **relative to `AI_CONTEXT_DIR`**, so the folder can be moved.
- Every successful full sync calls `register_ticket()`, which upserts the entry. A sync that finds the ticket unchanged (`jira_updated_at` equals Jira's `updated`, [FEATURES.md F9](FEATURES.md#f9-incremental-sync-skip-what-did-not-change)) writes nothing. `assets` maps each cached image to its Jira attachment `id` and `size`; an entry written before it existed simply means every image is downloaded once more. `jira_list_synced` shows it sorted by `jira_updated_at` desc. There is no `INDEX.md` any more.
- A catalog that decrypts but is not valid JSON is logged and rebuilt empty; one that does not decrypt is `No access`. Entries are never removed by a sync.

## 6. Asset rules

- Downloaded MIME types: `image/png`, `image/jpeg`, `image/jpg`, `image/webp`, `image/gif` (`IMAGE_MIME_TYPES`).
- Size cap: `MAX_ASSET_SIZE_MB` (default 15), checked against `Content-Length` and while streaming. Oversized or failed downloads are skipped, logged, and left out of `assets_count`.
- Filenames: `\ / * ? : " < > |` are replaced with `_`.
- Downloads stay in memory and are written only as `<filename>.enc`.
- **Reuse on re-sync**: an image whose attachment `id` and `size` match the catalog's `assets` entry and whose `.enc` file exists is kept, not downloaded again.
- **Purge on re-sync**: a file in `assets/` whose name is not `<image attachment>.enc` any more is deleted, and an empty `assets/` folder is removed. `ticket.md.enc` and `history.md.enc` are overwritten on every sync, and the plaintext files of older versions (`ticket.md`, `history.md`, `catalog.json`, `INDEX.md`) are deleted. Never hand-edit anything under `.ai-context/`.

## 7. Format changelog

| Date | Change |
|---|---|
| 2026-10-30 | Catalog entries gain `assets` (image file name → Jira attachment `id`, `size`), used to skip unchanged downloads. Additive: older entries without it still work. |
| 2026-10-20 | Frontmatter values are JSON-quoted (valid YAML). Before, `key`/`status`/... were unquoted and `labels` was a Python repr (`['a', 'b']`). |
| 2026-10-20 | `AI_CONTEXT_DIR` can move the folder (tools briefly returned absolute paths; since the encryption change below they return no paths). |
| 2026-10-20 | **Breaking**: every file is encrypted (`<name>.enc`, Fernet, key `JIRA_AI_CONTEXT_KEY`). `INDEX.md` is gone. Agents read through `jira_read_ticket` / `jira_read_asset`; tools no longer return file paths. Old plaintext folders are not read: re-sync each ticket (its plaintext files are deleted) or delete `.ai-context/`. |
