import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.adf_parser import adf_to_markdown
from core.config import JiraConfig
from core.indexer import register_ticket, list_indexed_tickets, _read_catalog
from core.jira_client import JiraClient, JiraApiError
from core.sync_service import SyncService


class TestAdfParser(unittest.TestCase):
    def test_plain_string(self):
        self.assertEqual(adf_to_markdown("Simple text"), "Simple text")
        self.assertEqual(adf_to_markdown(None), "*No description provided.*")

    def test_formatted_text(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "In đậm", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": " và "},
                        {"type": "text", "text": "In nghiêng", "marks": [{"type": "em"}]},
                        {"type": "text", "text": " kèm "},
                        {"type": "text", "text": "link", "marks": [{"type": "link", "attrs": {"href": "https://example.com"}}]},
                    ],
                }
            ],
        }
        rendered = adf_to_markdown(adf)
        self.assertIn("**In đậm**", rendered)
        self.assertIn("*In nghiêng*", rendered)
        self.assertIn("[link](https://example.com)", rendered)

    def test_headings_and_code(self):
        adf = {
            "type": "doc",
            "content": [
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Tiêu đề phụ"}]},
                {"type": "codeBlock", "attrs": {"language": "python"}, "content": [{"type": "text", "text": "x = 10"}]},
            ],
        }
        rendered = adf_to_markdown(adf)
        self.assertIn("## Tiêu đề phụ", rendered)
        self.assertIn("```python\nx = 10\n```", rendered)

    def test_table(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "table",
                    "content": [
                        {
                            "type": "tableRow",
                            "content": [
                                {"type": "tableHeader", "content": [{"type": "text", "text": "Col 1"}]},
                                {"type": "tableHeader", "content": [{"type": "text", "text": "Col 2"}]},
                            ],
                        },
                        {
                            "type": "tableRow",
                            "content": [
                                {"type": "tableCell", "content": [{"type": "text", "text": "Val A"}]},
                                {"type": "tableCell", "content": [{"type": "text", "text": "Val B"}]},
                            ],
                        },
                    ],
                }
            ],
        }
        rendered = adf_to_markdown(adf)
        self.assertIn("| Col 1 | Col 2 |", rendered)
        self.assertIn("| Val A | Val B |", rendered)


class TestSyncServiceWithMock(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.config = JiraConfig(
            base_url="https://test.atlassian.net",
            email="tester@example.com",
            api_token="dummy-token",
            max_asset_size_mb=5,
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("core.sync_service.TICKETS_DIR")
    @patch("core.indexer.INDEX_FILE")
    @patch("core.indexer.CATALOG_FILE")
    @patch.object(JiraClient, "get_issue")
    @patch.object(JiraClient, "download_attachment")
    def test_full_sync_flow(
        self, mock_download, mock_get_issue, mock_catalog_file, mock_index_file, mock_tickets_dir
    ):
        mock_tickets_dir.__truediv__.side_effect = lambda key: self.test_dir / "tickets" / key
        mock_index_file.parent = self.test_dir
        mock_index_file.write_text = MagicMock()
        mock_catalog_file.parent = self.test_dir
        mock_catalog_file.exists.return_value = False
        mock_catalog_file.write_text = MagicMock()

        mock_download.return_value = True

        mock_get_issue.return_value = {
            "key": "DEMO-101",
            "fields": {
                "summary": "Fix authentication crash on mobile",
                "status": {"name": "In Progress"},
                "issuetype": {"name": "Bug"},
                "priority": {"name": "High"},
                "assignee": {"displayName": "Alex Taylor"},
                "reporter": {"displayName": "Sam Morgan"},
                "created": "2026-09-01T08:00:00Z",
                "updated": "2026-09-21T09:00:00Z",
                "labels": ["mobile", "auth"],
                "description": {
                    "type": "doc",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "App crashes when token expires."}]}
                    ],
                },
                "attachment": [
                    {
                        "filename": "crash-trace.png",
                        "mimeType": "image/png",
                        "size": 1024,
                        "content": "https://test.atlassian.net/secure/attachment/1/crash-trace.png",
                    }
                ],
                "issuelinks": [],
                "subtasks": [],
            },
            "changelog": {
                "histories": [
                    {
                        "created": "2026-09-20T10:00:00Z",
                        "author": {"displayName": "Alex Taylor"},
                        "items": [{"field": "status", "fromString": "Open", "toString": "In Progress"}],
                    }
                ]
            },
        }

        service = SyncService(self.config)
        result = service.sync("DEMO-101")

        self.assertTrue(result.success)
        self.assertEqual(result.key, "DEMO-101")
        self.assertEqual(result.assets_downloaded, 1)

        # Check that ticket.md and history.md were created
        ticket_file = self.test_dir / "tickets" / "DEMO-101" / "ticket.md"
        history_file = self.test_dir / "tickets" / "DEMO-101" / "history.md"

        self.assertTrue(ticket_file.exists())
        self.assertTrue(history_file.exists())

        ticket_content = ticket_file.read_text(encoding="utf-8")
        self.assertIn("DEMO-101", ticket_content)
        self.assertIn("Fix authentication crash on mobile", ticket_content)
        self.assertIn("App crashes when token expires.", ticket_content)
        self.assertIn("assets/crash-trace.png", ticket_content)

        history_content = history_file.read_text(encoding="utf-8")
        self.assertIn("Alex Taylor", history_content)
        self.assertIn("`Open` ➔ `In Progress`", history_content)

    @patch.object(JiraClient, "get_issue")
    def test_sync_error_handling(self, mock_get_issue):
        mock_get_issue.side_effect = JiraApiError(404, "Ticket not found")
        service = SyncService(self.config)
        result = service.sync("DEMO-999")
        self.assertFalse(result.success)
        self.assertIn("Ticket not found", result.message)

    @patch.object(JiraClient, "get_issue")
    def test_sync_key_from_url(self, mock_get_issue):
        mock_get_issue.return_value = {
            "key": "DEMO-102",
            "fields": {"summary": "Analyze export preferences"},
            "changelog": {"histories": []},
        }
        service = SyncService(self.config)
        result = service.sync("https://test.atlassian.net/browse/DEMO-102")
        self.assertEqual(result.key, "DEMO-102")


if __name__ == "__main__":
    unittest.main()
