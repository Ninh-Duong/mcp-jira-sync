from typing import Any, Dict, List, Union
from utils.logger import get_logger

logger = get_logger("adf_parser")


def parse_marks(text: str, marks: List[Dict[str, Any]]) -> str:
    """Applies text marks (bold, italic, code, strikethrough, link)."""
    if not marks:
        return text

    result = text
    for mark in marks:
        m_type = mark.get("type", "")
        attrs = mark.get("attrs", {})
        if m_type == "strong":
            result = f"**{result}**"
        elif m_type == "em":
            result = f"*{result}*"
        elif m_type == "code":
            result = f"`{result}`"
        elif m_type == "strike":
            result = f"~~{result}~~"
        elif m_type == "link":
            href = attrs.get("href", "#")
            result = f"[{result}]({href})"
    return result


def _render_node(node: Dict[str, Any], indent_level: int = 0) -> str:
    """Recursively converts an ADF AST node into Markdown."""
    if not isinstance(node, dict):
        return str(node)

    n_type = node.get("type", "")
    content = node.get("content", [])
    attrs = node.get("attrs", {})

    if n_type == "doc":
        return "\n\n".join(filter(None, [_render_node(child, indent_level) for child in content]))

    if n_type == "text":
        text = node.get("text", "")
        marks = node.get("marks", [])
        return parse_marks(text, marks)

    if n_type == "paragraph":
        inner = "".join(_render_node(c, indent_level) for c in content)
        return inner.strip()

    if n_type == "heading":
        level = attrs.get("level", 1)
        prefix = "#" * max(1, min(6, level))
        inner = "".join(_render_node(c, indent_level) for c in content)
        return f"{prefix} {inner.strip()}"

    if n_type == "bulletList":
        items = []
        for c in content:
            item_text = _render_node(c, indent_level + 1)
            if item_text:
                items.append(f"{'  ' * indent_level}- {item_text}")
        return "\n".join(items)

    if n_type == "orderedList":
        items = []
        order = attrs.get("order", 1)
        for i, c in enumerate(content):
            item_text = _render_node(c, indent_level + 1)
            if item_text:
                items.append(f"{'  ' * indent_level}{order + i}. {item_text}")
        return "\n".join(items)

    if n_type == "listItem":
        return "\n".join(filter(None, [_render_node(c, indent_level) for c in content]))

    if n_type == "codeBlock":
        lang = attrs.get("language", "")
        inner = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        return f"```{lang}\n{inner}\n```"

    if n_type == "blockquote":
        inner = "\n\n".join(filter(None, [_render_node(c, indent_level) for c in content]))
        lines = [f"> {line}" for line in inner.split("\n")]
        return "\n".join(lines)

    if n_type == "rule":
        return "---"

    if n_type == "hardBreak":
        return "\n"

    if n_type == "mention":
        text = attrs.get("text") or attrs.get("id") or "user"
        return f"@{text}"

    if n_type == "inlineCard":
        url = attrs.get("url", "#")
        return f"[{url}]({url})"

    if n_type in ("mediaSingle", "mediaGroup"):
        return "\n".join(filter(None, [_render_node(c, indent_level) for c in content]))

    if n_type == "media":
        alt = attrs.get("alt", "image")
        m_id = attrs.get("id", "attachment")
        if alt and any(alt.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")):
            return f"![{alt}](assets/{alt})"
        return f"![{alt}]({m_id})"

    if n_type == "table":
        rows = []
        for row in content:
            if row.get("type") == "tableRow":
                cells = []
                is_header = False
                for cell in row.get("content", []):
                    c_type = cell.get("type")
                    if c_type == "tableHeader":
                        is_header = True
                    text = "".join(_render_node(child, 0) for child in cell.get("content", []))
                    cells.append(text.replace("\n", " ").strip())
                rows.append((cells, is_header))

        if not rows:
            return ""

        md_lines = []
        header_row, _ = rows[0]
        md_lines.append("| " + " | ".join(header_row) + " |")
        md_lines.append("| " + " | ".join(["---"] * len(header_row)) + " |")

        for cells, is_hdr in rows[1:]:
            # Pad if needed
            while len(cells) < len(header_row):
                cells.append("")
            md_lines.append("| " + " | ".join(cells[:len(header_row)]) + " |")

        return "\n".join(md_lines)

    # Fallback for generic container nodes
    if content:
        return "".join(_render_node(c, indent_level) for c in content)

    return ""


def adf_to_markdown(raw_desc: Union[str, Dict[str, Any], None]) -> str:
    """Converts Jira description (ADF JSON AST, plain string, or None) to Markdown."""
    if not raw_desc:
        return "*No description provided.*"

    if isinstance(raw_desc, str):
        return raw_desc.strip()

    if isinstance(raw_desc, dict):
        try:
            rendered = _render_node(raw_desc)
            return rendered.strip() if rendered else "*No description provided.*"
        except Exception as e:
            logger.error(f"Error parsing ADF structure: {e}", exc_info=True)
            return str(raw_desc)

    return str(raw_desc)
