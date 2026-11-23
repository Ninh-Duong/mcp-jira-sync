"""Encrypted attachment persistence and metadata; no document execution or conversion."""
import hashlib
import mimetypes
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from core.vault import ENC_SUFFIX, write_encrypted

IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
ATTACHMENT_SCHEMA = 1


def _safe_name(name: str) -> str:
    name = re.sub(r'[\s\x00-\x1f\\/*?:"<>|#%()\[\]]', "_", name).strip(" .") or "attachment"
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", name.split(".")[0]):
        name = "_" + name
    if len(name.encode("utf-8")) > 160:
        suffix = Path(name).suffix[:20]
        prefix = name.encode("utf-8")[:100].decode("utf-8", errors="ignore")
        name = prefix + "--" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:12] + suffix
    return name


def attachment_records(attachments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    names = [_safe_name(str(att.get("filename") or "attachment")) for att in attachments]
    counts = Counter(name.casefold() for name in names)
    used = set()
    records = []
    for position, (att, name) in enumerate(zip(attachments, names)):
        if counts[name.casefold()] > 1 or name.casefold() in used:
            path = Path(name)
            token = hashlib.sha256(str(att.get("id") or position).encode("utf-8")).hexdigest()[:12]
            name = path.stem + "--" + token + path.suffix
        while name.casefold() in used:
            name = "_" + name
        used.add(name.casefold())
        mime = str(att.get("mimeType") or mimetypes.guess_type(name)[0] or "application/octet-stream").lower()
        if not re.fullmatch(r"[a-z0-9.+_-]+/[a-z0-9.+_-]+", mime):
            mime = "application/octet-stream"
        records.append({"id": att.get("id"), "size": att.get("size"), "filename": name,
                        "original_filename": str(att.get("filename") or "attachment"), "mime": mime})
    return records


def cache_complete(cached: Dict[str, Any], assets_dir: Path) -> bool:
    if cached.get("attachment_schema") != ATTACHMENT_SCHEMA or not cached.get("attachments_complete"):
        return False
    records = cached.get("attachments", [])
    if len(records) != cached.get("attachments_count"):
        return False
    return all(record.get("status") == "cached" and
               (assets_dir / (record["filename"] + ENC_SUFFIX)).is_file() for record in records)


def link_attachments(markdown: str, records: List[Dict[str, Any]]) -> str:
    """Keep unique inline image references aligned with safe cache names."""
    counts = Counter(r["original_filename"] for r in records)
    for record in records:
        original = record["original_filename"]
        if counts[original] == 1 and record["status"] == "cached":
            markdown = markdown.replace(
                "](assets/" + original + ")", "](assets/" + record["filename"] + ")")
    return markdown


def _store_attachment(client, att, record, asset_file, previous, fernet) -> str:
    max_bytes = client.config.max_asset_size_mb * 1024 * 1024
    size = record.get("size")
    if isinstance(size, (int, float)) and size > max_bytes:
        return "size_limit"
    identity = {"id": record["id"], "size": size}
    if identity["id"] and previous == identity and asset_file.is_file():
        record["reused"] = True
        return "cached"
    data = client.download_attachment(att.get("content", ""), record["filename"])
    if data is None:
        return "download_failed"
    if len(data) > max_bytes:
        return "size_limit"
    write_encrypted(asset_file, data, fernet)
    return "cached"


def sync_attachments(client, attachments, assets_dir, previous, fernet) -> List[Dict[str, Any]]:
    records = attachment_records(attachments)
    for att, record in zip(attachments, records):
        asset_file = assets_dir / (record["filename"] + ENC_SUFFIX)
        record["status"] = _store_attachment(client, att, record, asset_file, previous.get(record["filename"]), fernet)
    valid = {r["filename"] + ENC_SUFFIX for r in records if r["status"] == "cached"}
    if assets_dir.exists():
        for path in assets_dir.iterdir():
            if path.is_file() and path.name not in valid:
                path.unlink()
        if not any(assets_dir.iterdir()):
            assets_dir.rmdir()
    return records
