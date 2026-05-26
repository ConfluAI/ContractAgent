"""
File parser node — converts docx/pdf files to plain text for downstream processing.

Pass-through: if no file_path, the node simply returns unchanged state.
"""

from __future__ import annotations

from pathlib import Path

from graph.state import WorkflowState


def _parse_docx(file_path: str) -> str:
    from docx import Document

    doc = Document(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def _parse_pdf(file_path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(file_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n".join(pages)


PARSERS = {
    ".docx": _parse_docx,
    ".doc": _parse_docx,
    ".pdf": _parse_pdf,
}


def parser_node(state: WorkflowState) -> dict:
    """Parse file if file_path is set, otherwise pass through."""
    file_path = state.get("file_path", "")
    if not file_path:
        return {}

    suffix = Path(file_path).suffix.lower()
    parser = PARSERS.get(suffix)
    if parser is None:
        return {"error": f"不支持的文件格式: {suffix}，支持: {', '.join(PARSERS)}"}

    try:
        text = parser(file_path)
        return {"input": text}
    except Exception as e:
        return {"error": f"文件解析失败: {e}"}
