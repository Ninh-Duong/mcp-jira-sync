import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from core.adf_parser import adf_to_markdown
import core.config as config_module
from core.config import JiraConfig, load_config
from core.indexer import list_indexed_tickets
from core.jira_client import JiraClient, JiraApiError
from core.sync_service import (
    FRONTMATTER_KEYS, SyncService, _format_ticket_markdown, extract_issue_key, read_synced_file,
)


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


class _TempAiContext(unittest.TestCase):
    """A temp .ai-context/ with a fresh key, and a Jira login that succeeds unless a test says otherwise."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.test_dir, True)
        self.key = Fernet.generate_key().decode("ascii")
        self.fernet = Fernet(self.key)
        self.config = JiraConfig(
            base_url="https://test.atlassian.net",
            email="tester@example.com",
            api_token="dummy-token",
            max_asset_size_mb=5,
            ai_context_key=self.key,
        )
        # JiraClient resolves cloudId over HTTP in __init__, and the access gate calls verify_account: no network in tests
        patch.object(JiraClient, "_resolve_cloud_id", return_value=None).start()
        self.verify = patch.object(JiraClient, "verify_account", return_value={"displayName": "Tester"}).start()
        patch("core.sync_service.TICKETS_DIR", self.test_dir / "tickets").start()
        patch("core.indexer.CATALOG_FILE", self.test_dir / "catalog.json.enc").start()
        self.addCleanup(patch.stopall)

    def _all_bytes(self) -> bytes:
        return b"".join(p.read_bytes() for p in self.test_dir.rglob("*") if p.is_file())


class TestSyncServiceWithMock(_TempAiContext):
    @patch.object(JiraClient, "get_issue")
    @patch.object(JiraClient, "download_attachment")
    def test_full_sync_flow(self, mock_download, mock_get_issue):
        mock_download.return_value = b"PNG-SECRET-PIXELS"

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

        ticket_dir = self.test_dir / "tickets" / "DEMO-101"
        self.assertEqual(
            sorted(p.relative_to(self.test_dir).as_posix() for p in self.test_dir.rglob("*") if p.is_file()),
            ["catalog.json.enc", "tickets/DEMO-101/assets/crash-trace.png.enc",
             "tickets/DEMO-101/history.md.enc", "tickets/DEMO-101/ticket.md.enc"],
        )
        # Nothing readable on disk: no ticket text, no people, no image bytes
        on_disk = self._all_bytes()
        for secret in (b"Fix authentication", b"token expires", b"Alex Taylor", b"PNG-SECRET-PIXELS"):
            self.assertNotIn(secret, on_disk)

        ticket_content = read_synced_file("DEMO-101", "ticket.md", self.fernet).decode("utf-8")
        self.assertIn("DEMO-101", ticket_content)
        self.assertIn("Fix authentication crash on mobile", ticket_content)
        self.assertIn("App crashes when token expires.", ticket_content)
        self.assertIn("assets/crash-trace.png", ticket_content)

        history_content = read_synced_file("DEMO-101", "history.md", self.fernet).decode("utf-8")
        self.assertIn("Alex Taylor", history_content)
        self.assertIn("`Open` ➔ `In Progress`", history_content)

        self.assertEqual(read_synced_file("DEMO-101", "assets/crash-trace.png", self.fernet), b"PNG-SECRET-PIXELS")
        self.assertEqual([t["key"] for t in list_indexed_tickets(self.fernet)], ["DEMO-101"])
        self.assertEqual(ticket_dir.name, result.ticket_file.parent.name)

    def test_sync_refuses_without_access(self):
        # No key, or a Jira login that fails right now: nothing is fetched or written
        with patch.object(JiraClient, "get_issue") as mock_get_issue:
            self.config.ai_context_key = ""
            result = SyncService(self.config).sync("DEMO-101")
            self.assertFalse(result.success)
            self.assertTrue(result.message.startswith("No access"), result.message)

            self.config.ai_context_key = self.key
            self.verify.side_effect = JiraApiError(401, "Unauthorized")
            result = SyncService(self.config).sync("DEMO-101")
            self.assertTrue(result.message.startswith("No access"), result.message)
            mock_get_issue.assert_not_called()
        self.assertFalse(self.test_dir.joinpath("tickets").exists())

    @patch.object(JiraClient, "get_issue")
    @patch.object(JiraClient, "download_attachment")
    def test_sync_purges_obsolete_assets(self, mock_download, mock_get_issue):
        mock_download.return_value = b"new content"

        # Pre-populate with an obsolete encrypted asset and plaintext files from before encryption
        ticket_dir = self.test_dir / "tickets" / "DEMO-101"
        assets_dir = ticket_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        old_file = assets_dir / "obsolete-photo.png.enc"
        old_file.write_bytes(self.fernet.encrypt(b"old content"))
        legacy = [assets_dir / "new-photo.png", ticket_dir / "ticket.md", ticket_dir / "history.md",
                  self.test_dir / "catalog.json", self.test_dir / "INDEX.md"]
        for f in legacy:
            f.write_text("plaintext from an older version", encoding="utf-8")

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
        self.assertTrue((assets_dir / "new-photo.png.enc").exists(), "Active asset should exist")
        for f in legacy:
            self.assertFalse(f.exists(), f"Plaintext {f.name} should be removed")

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


class TestReadTools(_TempAiContext):
    """jira_read_ticket / jira_read_asset / jira_list_synced: decrypt only behind the access gate (docs/FEATURES.md F7, F8)."""

    def setUp(self):
        super().setUp()
        patch("server.load_config", return_value=self.config).start()
        with patch.object(JiraClient, "get_issue") as mock_get_issue, \
                patch.object(JiraClient, "download_attachment", return_value=b"PNG-SECRET-PIXELS"):
            mock_get_issue.return_value = {
                "key": "DEMO-7",
                "fields": {
                    "summary": "Export report as CSV",
                    "attachment": [{"filename": "mock.png", "mimeType": "image/png", "content": "https://test.atlassian.net/att/1"}],
                },
                "changelog": {"histories": []},
            }
            self.assertTrue(SyncService(self.config).sync("DEMO-7").success)

    def _call(self, tool, **args):
        import server

        try:
            from mcp.server import MCPServer
        except ImportError:
            from mcp.server.fastmcp import FastMCP as MCPServer
        app = MCPServer("parent")
        server.register_jira_tools(app, prefix="x_")
        result = asyncio.run(app.call_tool(f"x_{tool}", args))
        content = getattr(result, "content", result)  # mcp 2.x CallToolResult; mcp 1.x content list or (content, structured)
        if isinstance(content, tuple):
            content = content[0]
        return content

    def test_read_ticket_returns_decrypted_markdown(self):
        (block,) = self._call("jira_read_ticket", issue_key="demo-7")
        self.assertTrue(block.text.startswith("✅ DEMO-7"))
        self.assertIn("Export report as CSV", block.text)
        self.assertIn("assets/mock.png", block.text)
        self.assertIn("Change History", block.text)

    def test_read_asset_returns_image(self):
        (block,) = self._call("jira_read_asset", issue_key="DEMO-7", filename="assets/mock.png")
        image = block.model_dump(by_alias=True)  # mimeType on the wire in mcp 1.x and 2.x
        self.assertEqual(image["type"], "image")
        self.assertEqual(image["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(image["data"]), b"PNG-SECRET-PIXELS")

    def test_reads_refused_without_access(self):
        import server

        self.verify.side_effect = JiraApiError(401, "Unauthorized")
        for reply in (server.jira_read_ticket("DEMO-7"), server.jira_list_synced(),
                      server.jira_read_asset("DEMO-7", "mock.png")):
            self.assertTrue(reply.startswith("❌ No access"), reply)
        self.verify.side_effect = None
        self.config.ai_context_key = Fernet.generate_key().decode("ascii")  # someone else's key
        self.assertTrue(server.jira_read_ticket("DEMO-7").startswith("❌ No access"))

    def test_read_rejects_paths_outside_the_ticket(self):
        import server

        self.assertTrue(server.jira_read_asset("DEMO-7", "../ticket.md").startswith("❌ Not an image"))
        self.assertTrue(server.jira_read_asset("DEMO-7", "../../DEMO-8/assets/x.png").startswith("❌"))
        self.assertIn("Call jira_sync_ticket first", server.jira_read_ticket("DEMO-8"))
        self.assertTrue(server.jira_read_ticket("hello").startswith("❌ Invalid ticket key"))


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
        central.write_text(
            json.dumps({"jira": {"email": "central@x", "api_token": "central-token", "ai_context_key": "central-key"}}),
            encoding="utf-8",
        )
        clean = self._env_without_jira()
        clean.update({"CENTRAL_CONFIG_PATH": str(central), "JIRA_API_TOKEN": "env-token"})
        with patch.object(config_module, "ENV_FILE", env_file), patch.dict(os.environ, clean, clear=True):
            cfg = load_config()
            with patch.dict(os.environ, {"JIRA_AI_CONTEXT_KEY": "env-key"}):
                env_key = load_config().ai_context_key
        self.assertEqual(cfg.api_token, "env-token")  # process env wins
        self.assertEqual(cfg.email, "central@x")  # central beats .env
        self.assertEqual(cfg.base_url, "https://dotenv.atlassian.net")  # .env is the fallback
        self.assertEqual(cfg.ai_context_key, "central-key")
        self.assertEqual(env_key, "env-key")

    def test_config_sources_per_field(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        env_file = tmp / ".env"
        env_file.write_text("JIRA_BASE_URL=https://dotenv.atlassian.net\nJIRA_AI_CONTEXT_KEY=local-key\n", encoding="utf-8")
        central = tmp / "central.json"
        central.write_text(json.dumps({"jira": {"email": "hub@x", "api_token": "", "base_url": " "}}), encoding="utf-8")
        clean = {**self._env_without_jira(), "CENTRAL_CONFIG_PATH": str(central), "JIRA_API_TOKEN": "env-token"}
        with patch.object(config_module, "ENV_FILE", env_file), patch.dict(os.environ, clean, clear=True):
            cfg = load_config()
        self.assertEqual(cfg.sources, {
            "base_url": "local",  # a blank hub value counts as unset
            "email": "hub",
            "api_token": "env",
            "max_asset_size_mb": "unset",
            "ai_context_key": "local",
        })
        self.assertEqual(
            config_module.format_sources(cfg), "base_url=local, email=hub, api_token=env, ai_context_key=local"
        )

    def test_relative_central_path_resolves_against_base_dir(self):
        root = Path(tempfile.mkdtemp())
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        self.addCleanup(shutil.rmtree, other, True)
        (root / "hub").mkdir()
        (root / "hub" / "jira.json").write_text(json.dumps({"jira": {"email": "hub@x"}}), encoding="utf-8")
        clean = {**self._env_without_jira(), "CENTRAL_CONFIG_PATH": "hub/jira.json"}
        cwd = os.getcwd()
        os.chdir(other)  # the hub launches us from another directory
        self.addCleanup(os.chdir, cwd)
        with patch.object(config_module, "BASE_DIR", root), patch.object(config_module, "ENV_FILE", root / ".env"),                 patch.dict(os.environ, clean, clear=True):
            cfg = load_config()
        self.assertEqual(cfg.email, "hub@x")
        self.assertEqual(cfg.sources["email"], "hub")

    def test_missing_central_file_warns_and_falls_back_to_dotenv(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        env_file = tmp / ".env"
        env_file.write_text("JIRA_EMAIL=dotenv@x\n", encoding="utf-8")
        clean = {**self._env_without_jira(), "CENTRAL_CONFIG_PATH": str(tmp / "missing.json")}
        with patch.object(config_module, "ENV_FILE", env_file), patch.dict(os.environ, clean, clear=True),                 self.assertLogs(config_module.logger, "WARNING") as logs:
            cfg = load_config()
        self.assertIn("does not exist", "\n".join(logs.output))
        self.assertNotIn("missing.json", "\n".join(logs.output))
        self.assertEqual(cfg.email, "dotenv@x")
        self.assertEqual(cfg.sources["email"], "local")

    def test_check_connection_reports_sources(self):
        import server

        cfg = JiraConfig(
            base_url="https://x.atlassian.net", email="e@x", api_token="secret-token", ai_context_key="secret-key",
            sources={"base_url": "hub", "email": "hub", "api_token": "hub", "ai_context_key": "local"},
        )
        with patch.object(server, "load_config", return_value=cfg),                 patch.object(JiraClient, "_resolve_cloud_id", return_value=None),                 patch.object(JiraClient, "verify_account", return_value={"displayName": "Tester", "emailAddress": "e@x"}):
            text = server.jira_check_connection()
        self.assertTrue(text.startswith("✅"))  # mcp-hub's smoke check relies on this prefix
        self.assertIn("Config source: base_url=hub, email=hub, api_token=hub, ai_context_key=local", text)
        self.assertNotIn("secret", text)
        with patch.object(server, "load_config", return_value=JiraConfig("", "", "")):
            missing = server.jira_check_connection()
        self.assertIn("CENTRAL_CONFIG_PATH", missing)
        self.assertIn(".env", missing)

    @staticmethod
    def _env_without_jira():
        skip = {"CENTRAL_CONFIG_PATH", "PYTHON_DOTENV_DISABLED"}
        return {k: v for k, v in os.environ.items() if not k.startswith("JIRA_") and k not in skip}

    def test_dotenv_ignored_when_disabled(self):
        # Manual opt-out: PYTHON_DOTENV_DISABLED=1 keeps the standalone .env out of a run (the hub no longer sets it)
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        env_file = tmp / ".env"
        env_file.write_text("JIRA_EMAIL=dotenv@x\nAI_CONTEXT_DIR=<WORKSPACE>/.ai-context\n", encoding="utf-8")
        for flag in ("1", "True", "yes"):
            env = {**self._env_without_jira(), "PYTHON_DOTENV_DISABLED": flag}
            with patch.object(config_module, "ENV_FILE", env_file), patch.dict(os.environ, env, clear=True):
                self.assertEqual(config_module._local_env(), {})
                self.assertEqual(load_config().email, "")
        with patch.object(config_module, "ENV_FILE", env_file), patch.dict(os.environ, self._env_without_jira(), clear=True):
            self.assertEqual(load_config().email, "dotenv@x")  # standalone: .env still read

    def test_save_config_keeps_other_env_lines(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        env_file = tmp / ".env"
        env_file.write_text("AI_CONTEXT_DIR=<WORKSPACE>/.ai-context\n", encoding="utf-8")
        with patch.object(config_module, "ENV_FILE", env_file), \
                patch.dict(os.environ, self._env_without_jira(), clear=True):
            config_module.save_config("https://x.atlassian.net/", "e@x", "tok")
            values = config_module._local_env()
            config_module.save_config("https://x.atlassian.net/", "other@x", "tok2")  # switching account keeps the key
            again = config_module._local_env()
        self.assertEqual(values["AI_CONTEXT_DIR"], "<WORKSPACE>/.ai-context")
        self.assertEqual(values["JIRA_BASE_URL"], "https://x.atlassian.net")
        self.assertEqual(values["JIRA_API_TOKEN"], "tok")
        Fernet(values["JIRA_AI_CONTEXT_KEY"])  # first login writes a valid key
        self.assertEqual(again["JIRA_AI_CONTEXT_KEY"], values["JIRA_AI_CONTEXT_KEY"])

    def test_tools_mount_with_prefix(self):
        import server  # must not exit or start anything on import

        try:
            from mcp.server import MCPServer
        except ImportError:
            from mcp.server.fastmcp import FastMCP as MCPServer
        app = MCPServer("parent")
        server.register_jira_tools(app, prefix="x_")
        tools = {t.name: t for t in asyncio.run(app.list_tools())}
        self.assertEqual(set(tools), {
            "x_jira_sync_ticket", "x_jira_read_ticket", "x_jira_read_asset", "x_jira_list_synced", "x_jira_check_connection",
        })
        hints = {name: t.annotations.model_dump(by_alias=True) for name, t in tools.items()}  # camelCase in mcp 1.x and 2.x
        self.assertFalse(hints["x_jira_sync_ticket"]["readOnlyHint"])
        for name in ("x_jira_read_ticket", "x_jira_read_asset", "x_jira_list_synced", "x_jira_check_connection"):
            self.assertTrue(hints[name]["readOnlyHint"], name)
            self.assertTrue(hints[name]["openWorldHint"], name)  # every read logs in to Jira first
        instructions = server.jira_instructions("x_")
        for name in ("x_jira_sync_ticket", "x_jira_read_ticket", "x_jira_read_asset", "No access"):
            self.assertIn(name, instructions)


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
