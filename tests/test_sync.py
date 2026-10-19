import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.adf_parser import adf_to_markdown
import core.config as config_module
from core.config import JiraConfig, load_config
from core.indexer import register_ticket, list_indexed_tickets, _read_catalog
from core.jira_client import JiraClient, JiraApiError
from core.sync_service import FRONTMATTER_KEYS, SyncService, _format_ticket_markdown, extract_issue_key


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

    def test_media_linking(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "mediaSingle",
                    "content": [
                        {
                            "type": "media",
                            "attrs": {
                                "id": "uuid-1234",
                                "type": "file",
                                "collection": "",
                                "alt": "screenshot.png",
                            },
                        }
                    ],
                }
            ],
        }
        rendered = adf_to_markdown(adf)
        self.assertEqual(rendered, "![screenshot.png](assets/screenshot.png)")


class TestSyncServiceWithMock(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.config = JiraConfig(
            base_url="https://test.atlassian.net",
            email="tester@example.com",
            api_token="dummy-token",
            max_asset_size_mb=5,
        )
        # JiraClient resolves cloudId over HTTP in __init__; tests never touch the network
        patch.object(JiraClient, "_resolve_cloud_id", return_value=None).start()
        self.addCleanup(patch.stopall)

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

    @patch("core.sync_service.TICKETS_DIR")
    @patch("core.indexer.INDEX_FILE")
    @patch("core.indexer.CATALOG_FILE")
    @patch.object(JiraClient, "get_issue")
    @patch.object(JiraClient, "download_attachment")
    def test_sync_purges_obsolete_assets(
        self, mock_download, mock_get_issue, mock_catalog_file, mock_index_file, mock_tickets_dir
    ):
        mock_tickets_dir.__truediv__.side_effect = lambda key: self.test_dir / "tickets" / key
        mock_index_file.parent = self.test_dir
        mock_index_file.write_text = MagicMock()
        mock_catalog_file.parent = self.test_dir
        mock_catalog_file.exists.return_value = False
        mock_catalog_file.write_text = MagicMock()
        mock_download.side_effect = lambda url, dest: dest.write_text("new content") or True

        # Pre-populate assets dir with an obsolete asset
        assets_dir = self.test_dir / "tickets" / "DEMO-101" / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        old_file = assets_dir / "obsolete-photo.png"
        old_file.write_text("old content")

        mock_get_issue.return_value = {
            "key": "DEMO-101",
            "fields": {
                "summary": "Sample issue",
                "attachment": [
                    {
                        "filename": "new-photo.png",
                        "mimeType": "image/png",
                        "content": "https://test.atlassian.net/att/1",
                    }
                ],
            },
            "changelog": {"histories": []},
        }

        service = SyncService(self.config)
        result = service.sync("DEMO-101")

        self.assertTrue(result.success)
        self.assertFalse(old_file.exists(), "Obsolete asset should be purged")
        self.assertTrue((assets_dir / "new-photo.png").exists(), "Active asset should exist")

    @patch.object(JiraClient, "get_issue")
    def test_sync_error_handling(self, mock_get_issue):
        mock_get_issue.side_effect = JiraApiError(404, "Ticket not found")
        service = SyncService(self.config)
        result = service.sync("DEMO-999")
        self.assertFalse(result.success)
        self.assertIn("Ticket not found", result.message)

    @patch("core.sync_service.TICKETS_DIR")
    @patch("core.indexer.INDEX_FILE")
    @patch("core.indexer.CATALOG_FILE")
    @patch.object(JiraClient, "get_issue")
    def test_sync_key_from_url(self, mock_get_issue, mock_catalog_file, mock_index_file, mock_tickets_dir):
        mock_tickets_dir.__truediv__.side_effect = lambda key: self.test_dir / "tickets" / key
        mock_index_file.parent = self.test_dir
        mock_index_file.write_text = MagicMock()
        mock_catalog_file.parent = self.test_dir
        mock_catalog_file.exists.return_value = False
        mock_catalog_file.write_text = MagicMock()

        mock_get_issue.return_value = {
            "key": "DEMO-102",
            "fields": {"summary": "Analyze export preferences"},
            "changelog": {"histories": []},
        }
        service = SyncService(self.config)
        result = service.sync("https://test.atlassian.net/browse/DEMO-102")
        self.assertEqual(result.key, "DEMO-102")


class TestContracts(unittest.TestCase):
    """Locks the contracts documented in docs/AI_CONTEXT_FORMAT.md, docs/JIRA_ACCESS.md and AGENTS.md."""

    def test_frontmatter_is_valid_and_complete(self):
        meta = {
            "key": "DEMO-1",
            "summary": 'Fix "login": a\\b path',
            "status": "To Do: Review",
            "type": "Bug",
            "priority": "High",
            "assignee": "Alex",
            "reporter": "Sam",
            "created": "2026-09-01T08:00:00Z",
            "updated": "2026-09-02T08:00:00Z",
            "url": "https://x.atlassian.net/browse/DEMO-1",
            "labels": ["a", "b"],
        }
        md = _format_ticket_markdown(meta, "desc", [{"filename": "a.png", "mime": "image/png"}], [], {})
        lines = md.split("\n")
        self.assertEqual(lines[0], "---")
        block = lines[1:lines.index("---", 1)]
        parsed = {k: json.loads(v) for k, v in (line.split(": ", 1) for line in block)}
        self.assertEqual(tuple(parsed), FRONTMATTER_KEYS)  # keep in sync with docs/AI_CONTEXT_FORMAT.md
        self.assertEqual(parsed["summary"], meta["summary"])
        self.assertEqual(parsed["labels"], ["a", "b"])
        self.assertEqual(parsed["assets_count"], 1)

    def test_issue_key_extraction(self):
        self.assertEqual(extract_issue_key("abc-12"), "ABC-12")
        self.assertEqual(extract_issue_key(" MY_PROJ-1 "), "MY_PROJ-1")
        self.assertEqual(extract_issue_key("https://team-2.atlassian.net/browse/ABC-5"), "ABC-5")
        self.assertEqual(
            extract_issue_key("https://team-2.atlassian.net/jira/software/projects/ABC/boards/1?selectedIssue=ABC-7"),
            "ABC-7",
        )
        self.assertIsNone(extract_issue_key("https://team-2.atlassian.net/"))
        self.assertIsNone(extract_issue_key("hello"))

    def test_config_priority_env_then_central_then_dotenv(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        env_file = tmp / ".env"
        env_file.write_text(
            "JIRA_BASE_URL=https://dotenv.atlassian.net\nJIRA_EMAIL=dotenv@x\nJIRA_API_TOKEN=dotenv-token\n",
            encoding="utf-8",
        )
        central = tmp / "central.json"
        central.write_text(json.dumps({"jira": {"email": "central@x", "api_token": "central-token"}}), encoding="utf-8")
        clean = {k: v for k, v in os.environ.items() if not k.startswith("JIRA_") and k != "CENTRAL_CONFIG_PATH"}
        clean.update({"CENTRAL_CONFIG_PATH": str(central), "JIRA_API_TOKEN": "env-token"})
        with patch.object(config_module, "ENV_FILE", env_file), patch.dict(os.environ, clean, clear=True):
            cfg = load_config()
        self.assertEqual(cfg.api_token, "env-token")  # process env wins
        self.assertEqual(cfg.email, "central@x")  # central beats .env
        self.assertEqual(cfg.base_url, "https://dotenv.atlassian.net")  # .env is the fallback

    def test_save_config_keeps_other_env_lines(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        env_file = tmp / ".env"
        env_file.write_text("AI_CONTEXT_DIR=<WORKSPACE>/.ai-context\n", encoding="utf-8")
        with patch.object(config_module, "ENV_FILE", env_file):
            config_module.save_config("https://x.atlassian.net/", "e@x", "tok")
            values = config_module._local_env()
        self.assertEqual(values["AI_CONTEXT_DIR"], "<WORKSPACE>/.ai-context")
        self.assertEqual(values["JIRA_BASE_URL"], "https://x.atlassian.net")
        self.assertEqual(values["JIRA_API_TOKEN"], "tok")

    def test_tools_mount_with_prefix(self):
        import server  # must not exit or start anything on import

        try:
            from mcp.server import MCPServer
        except ImportError:
            from mcp.server.fastmcp import FastMCP as MCPServer
        app = MCPServer("parent")
        server.register_jira_tools(app, prefix="x_")
        tools = {t.name: t for t in asyncio.run(app.list_tools())}
        self.assertEqual(set(tools), {"x_jira_sync_ticket", "x_jira_list_synced", "x_jira_check_connection"})
        hints = {name: t.annotations.model_dump(by_alias=True) for name, t in tools.items()}  # camelCase in mcp 1.x and 2.x
        self.assertFalse(hints["x_jira_sync_ticket"]["readOnlyHint"])
        self.assertTrue(hints["x_jira_list_synced"]["readOnlyHint"])
        self.assertIn("x_jira_sync_ticket", server.jira_instructions("x_"))


class TestPublicRepoHygiene(unittest.TestCase):
    """This repo is public: no file that would be committed may hold local paths or private data. See docs/SECURITY.md."""

    ROOT = Path(__file__).resolve().parent.parent
    ALLOWED_EMAIL_DOMAINS = {"example.com", "users.noreply.github.com"}
    ALLOWED_TENANTS = {"your-domain", "test", "x", "team-2", "dotenv"}
    CHECKS = {
        "local drive path": re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]+[A-Za-z0-9_]"),
        "local home path": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+"),
        "email": re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)"),
        "jira tenant": re.compile(r"([\w-]+)\.atlassian\.net"),
        "atlassian token": re.compile(r"\bAT(?:ATT|CTT)[A-Za-z0-9_=-]{20,}"),
    }

    def _publishable_files(self):
        """Tracked files plus untracked ones git would add (not ignored)."""
        try:
            out = subprocess.run(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                cwd=self.ROOT, capture_output=True, text=True, check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git is not available")
        for rel in out.splitlines():
            path = self.ROOT / rel
            try:
                yield rel, path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue  # deleted in the working tree, or binary

    def _private_terms(self):
        """Employer/project terms kept only in the git-ignored .private-terms file, one regex per line."""
        path = self.ROOT / ".private-terms"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        return [re.compile(line, re.I) for line in lines if line.strip() and not line.startswith("#")]

    def _allowed(self, name, match):
        if name == "email":
            return match.group(1).lower() in self.ALLOWED_EMAIL_DOMAINS
        if name == "jira tenant":
            return match.group(1).lower() in self.ALLOWED_TENANTS
        return False

    def test_no_local_paths_or_private_data(self):
        private = self._private_terms()
        problems = []
        for rel, text in self._publishable_files():
            for lineno, line in enumerate(text.splitlines(), 1):
                for name, pattern in self.CHECKS.items():
                    for m in pattern.finditer(line):
                        if not self._allowed(name, m):
                            problems.append(f"{rel}:{lineno}: {name}: {m.group(0)}")
                for pattern in private:
                    if pattern.search(line):
                        problems.append(f"{rel}:{lineno}: private term (see .private-terms)")
        self.assertEqual(problems, [], "Use placeholders from docs/SECURITY.md:\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
