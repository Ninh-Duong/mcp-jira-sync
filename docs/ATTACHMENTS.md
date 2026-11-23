# Complete attachment sync

## Purpose and behavior

An ordinary ticket sync attempts every Jira attachment by default, including images, documents, spreadsheets, text and archives. It uses the existing MAX_ASSET_SIZE_MB limit for each file, downloads into memory and encrypts the bytes through the vault. Original names and MIME/size/status metadata remain available to the agent. Names used in local references are sanitized and collisions are kept separate.

An incomplete download is reported in ticket Markdown and sync counts. Legacy image-only entries and missing cached files are repaired on the next ordinary sync even when Jira updated is unchanged. Complete unchanged entries retain the cheap timestamp check; unchanged attachments retain id/size reuse. Removed files are purged.

## Reading and interpretation

The existing jira_read_asset tool accepts each listed local filename. Images retain image blocks. Other cached files return MCP embedded resources with their bytes, original filename and MIME type. A client may need its own document reader to interpret a binary resource. Read tools never download missing content.

An agent relates attachments to cases using the original filename, actual content and references in the ticket. A filename is a clue, not proof; unsupported or ambiguous mappings remain questions.

## Non-goals and tests

No OCR, PDF/Office conversion, archive extraction, executable content, unbounded download, automatic sync on read, comments ingestion or semantic classification inside the sync service. TestFullAttachments covers mixed files, encryption, read tools, reuse, legacy/missing repair, failed/large files, collisions and deletion. No new runtime dependency is required.
