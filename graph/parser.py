"""
File parser node — 解析 docx/pdf → 按条款切分 → 构建检索 query。

解析后的全文不进入 state，只保留:
  - file_path: 文件路径（短字符串）
  - contract_name: 合同名称（从首行/文件名提取）
  - clauses: 按"第X条"切分的条款列表
  - input: 检索用 query（合同名 + 前 3 条条款摘要，~300 chars）

Pass-through: 无 file_path 时透传（文本输入模式，走旧单次审查路径）。

致命错误（格式不支持、文件损坏）→ Command(goto=END)。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from docx import Document  # noqa: F401 — 顶层导入，避免首次调用时 lxml 冷启动
from pypdf import PdfReader  # noqa: F401

from langgraph.types import Command
from langgraph.constants import END
from langchain_core.runnables import RunnableConfig

from graph.state import WorkflowState


def _extract_contract_name(text: str, file_path: str) -> str:
    """从文档首行提取合同名，兜底用文件名。"""
    first_line = text.strip().split('\n')[0][:100]
    if '合同' in first_line or '协议' in first_line:
        return first_line
    return Path(file_path).stem


# ── 条款切分 ──────────────────────────────────────────────────────────

# "第X条" 模式：中文数字 + 阿拉伯数字
_CLAUSE_PATTERN = re.compile(
    r'(?:^|\n)\s*第[一二三四五六七八九十百千\d]+条'
)

_CLAUSE_SPLIT = re.compile(
    r'(?=(?:^|\n)\s*第[一二三四五六七八九十百千\d]+条)'
)


def _split_long(text: str, max_chars: int = 1500) -> list[str]:
    """单条过长时按句号/换行二次切分。"""
    if len(text) <= max_chars:
        return [text]

    parts = []
    remaining = text
    while len(remaining) > max_chars:
        # 在 max_chars 附近找最近的句号或换行
        cut = max_chars
        for sep in ['。', '\n', '；']:
            pos = remaining.rfind(sep, 0, max_chars)
            if pos > max_chars * 0.5:
                cut = pos + 1
                break
        parts.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining.strip():
        parts.append(remaining)
    return parts


def split_contract_clauses(text: str, max_clause_chars: int = 1500) -> list[dict]:
    """按"第X条"切分合同文本。

    策略:
      1. 主策略: 按"第X条"正则切分
      2. 首段（第一条之前的内容）保留为合同头部
      3. 单条过长(>1500字) → 按句号/换行再切
      4. 完全没有"第X条" → 按双换行切 → 固定窗口兜底

    Returns:
      [{clause_num, sub_num, title, content}, ...]
    """
    if not text.strip():
        return []

    # 找第一条的位置
    first_match = _CLAUSE_PATTERN.search(text)

    if first_match:
        # 有"第X条"结构 → 按条款切分
        body_start = first_match.start()
        raw_clauses = _CLAUSE_SPLIT.split(text[body_start:])
    else:
        # 无条款结构 → 按双换行切分
        raw_clauses = [p.strip() for p in text.split('\n\n') if p.strip()]
        if len(raw_clauses) <= 1:
            raw_clauses = _split_long(text, max_clause_chars)

    clauses: list[dict] = []
    clause_num = 0
    for part in raw_clauses:
        part = part.strip()
        if not part:
            continue
        clause_num += 1
        title = part.split('\n')[0][:80]

        if len(part) > max_clause_chars:
            sub_parts = _split_long(part, max_clause_chars)
            for j, sp in enumerate(sub_parts):
                clauses.append({
                    "clause_num": clause_num,
                    "sub_num": j + 1 if len(sub_parts) > 1 else 0,
                    "title": title if j == 0 else f"{title}(续)",
                    "content": sp.strip(),
                })
        else:
            clauses.append({
                "clause_num": clause_num,
                "sub_num": 0,
                "title": title,
                "content": part,
            })

    return clauses


# ── 文件解析 ──────────────────────────────────────────────────────────

def _parse_docx(file_path: str) -> str:
    doc = Document(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def _parse_pdf(file_path: str) -> str:
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


# ── 图节点 ────────────────────────────────────────────────────────────

async def parser_node(state: WorkflowState, config: RunnableConfig) -> dict:
    """解析合同文件 → 切分条款 → 构建检索 query。全文不进 state。

    无文件时透传（文本输入模式，走旧单次审查路径）。
    """
    file_path = config.get("configurable", {}).get("file_path", "")
    if not file_path:
        return {}

    suffix = Path(file_path).suffix.lower()
    parser = PARSERS.get(suffix)
    if parser is None:
        return Command(
            goto=END,
            update={"error": f"不支持的文件格式: {suffix}，支持: {', '.join(PARSERS)}"},
        )

    try:
        text = await asyncio.to_thread(parser, file_path)
    except Exception as e:
        return Command(goto=END, update={"error": f"文件解析失败: {e}"})

    # 切分条款
    clauses = split_contract_clauses(text)

    # 提取合同名
    contract_name = _extract_contract_name(text, file_path)

    # 构建检索 query（合同名 + 前 3 条条款摘要，控制 token）
    sample_parts = []
    for c in clauses[:3]:
        sample_parts.append(f"{c['title']}: {c['content'][:120]}")
    query = f"合同名称: {contract_name}\n" + "\n".join(sample_parts)

    # 全文丢弃，不进 state
    del text

    return {
        "file_path": file_path,
        "contract_name": contract_name,
        "clauses": clauses,
        "input": query,
    }
