"""
切分 中华人民共和国劳动法 .docx → JSONL chunks。

只保留合同相关章节：
  第三章 劳动合同和集体合同 (16-35)
  第四章 工作时间和休息休假 (36-45)
  第五章 工资 (46-51)
  第七章 女职工和未成年工特殊保护 (58-65)
  第九章 社会保险和福利 (70-76)
  第十章 劳动争议 (77-84)
  第十二章 法律责任 (89-105)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from docx import Document

SOURCE_NAME = "中华人民共和国劳动法"

# ── 中文数字 → 整数 ──────────────────────────────────────────────────────

CN_NUM_MAP = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
    "十": 10, "百": 100, "千": 1000,
    "零": 0,
}


def cn_to_int(cn: str) -> int:
    result = 0
    seg = 0
    for ch in cn:
        if ch in ("十", "百", "千"):
            if seg == 0:
                seg = 1
            seg *= CN_NUM_MAP[ch]
            if ch == "千":
                result += seg
                seg = 0
        else:
            if seg >= 10:
                result += seg
                seg = 0
            seg += CN_NUM_MAP.get(ch, 0)
    result += seg
    return result


# ── 目标章节 ────────────────────────────────────────────────────────────

INCLUDE_CHAPTERS = {3, 4, 5, 7, 9, 10, 12}

CHAPTER_DOMAIN_MAP = {
    3: "劳动合同",
    4: "工作时间与休息休假",
    5: "工资",
    7: "特殊保护",
    9: "社会保险与福利",
    10: "劳动争议",
    12: "法律责任",
}

# ── 正则 ─────────────────────────────────────────────────────────────────

CHAPTER_RE = re.compile(r"^第([一二三四五六七八九十]+)章\s+(.+)$")
ARTICLE_RE = re.compile(r"^第([一二三四五六七八九十百千零]+)条\b")


def is_article_start(text: str) -> bool:
    return bool(ARTICLE_RE.match(text))


def parse_chapter(text: str) -> tuple[int, str] | None:
    """返回 (章节编号, 章节标题) 或 None"""
    m = CHAPTER_RE.match(text)
    if not m:
        return None
    return cn_to_int(m.group(1)), m.group(2).strip()


# ── 主提取逻辑 ──────────────────────────────────────────────────────────


def extract_articles(docx_path: str) -> list[dict]:
    doc = Document(docx_path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    # 跳过目录：找到正文中的第一个"第X章"
    content_start = 0
    for i, text in enumerate(paragraphs):
        # 目录中的章节标题字数少，正文中的章节标题是完整复现
        # 策略：找到第二个"第一章"（第一个在目录，第二个在正文）
        if CHAPTER_RE.match(text) and i > 10:
            content_start = i
            break

    chapter_num = None
    chapter_title = None
    chunks = []
    current_lines: list[str] = []
    current_article_id: str | None = None

    for text in paragraphs[content_start:]:
        ch = parse_chapter(text)
        if ch is not None:
            # 保存前一条
            if current_article_id and current_lines and chapter_num in INCLUDE_CHAPTERS:
                chunks.append(_build_chunk(
                    current_article_id, current_lines, chapter_num, chapter_title
                ))
            chapter_num, chapter_title = ch
            current_lines = []
            current_article_id = None
            continue

        if is_article_start(text):
            # 保存前一条
            if current_article_id and current_lines and chapter_num in INCLUDE_CHAPTERS:
                chunks.append(_build_chunk(
                    current_article_id, current_lines, chapter_num, chapter_title
                ))
            m = ARTICLE_RE.match(text)
            current_article_id = m.group()
            current_lines = [text]
        else:
            if current_lines:
                current_lines.append(text)

    # 最后一条
    if current_article_id and current_lines and chapter_num in INCLUDE_CHAPTERS:
        chunks.append(_build_chunk(
            current_article_id, current_lines, chapter_num, chapter_title
        ))

    return chunks


def _build_chunk(
    article_id: str, lines: list[str],
    chapter_num: int, chapter_title: str,
) -> dict:
    full_text = "\n".join(lines)
    article_num = parse_article_num(article_id)

    chapter_full = f"第{_int_to_cn(chapter_num)}章 {chapter_title}"

    page_content = f"{SOURCE_NAME}\n{chapter_full}\n{full_text}"

    domain = CHAPTER_DOMAIN_MAP.get(chapter_num, "劳动法通用")

    return {
        "page_content": page_content,
        "metadata": {
            "source": SOURCE_NAME,
            "section_id": article_id,
            "article_num": article_num,
            "chapter": chapter_full,
            "law_rank": 4,
            "law_rank_desc": "法律",
            "domain": domain,
        },
    }


def parse_article_num(article_id: str) -> int:
    m = ARTICLE_RE.match(article_id)
    if m:
        return cn_to_int(m.group(1))
    return 0


def _int_to_cn(n: int) -> str:
    """整数→中文数字。仅需 1-12，因为最多12章。"""
    MAP = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五",
           6: "六", 7: "七", 8: "八", 9: "九",
           10: "十", 11: "十一", 12: "十二"}
    return MAP.get(n, str(n))


# ── Main ────────────────────────────────────────────────────────────────


def main() -> None:
    input_path = Path("data/中华人民共和国劳动法_20181229.docx")
    output_path = Path("data/labor_law_contract_chunks.jsonl")

    print(f"Reading {input_path}...", file=sys.stderr)
    chunks = extract_articles(str(input_path))
    print(f"Extracted {len(chunks)} articles.", file=sys.stderr)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    print(f"Done. Output: {output_path}", file=sys.stderr)

    # 按章节统计
    from collections import Counter
    ch_counts = Counter(c["metadata"]["chapter"] for c in chunks)
    for ch, cnt in sorted(ch_counts.items()):
        print(f"  {ch}: {cnt} 条", file=sys.stderr)

    # 抽样
    if chunks:
        print("\n── Sample ──", file=sys.stderr)
        print(chunks[0]["page_content"][:300], file=sys.stderr)
        print("...", file=sys.stderr)
        print(json.dumps(chunks[0]["metadata"], ensure_ascii=False, indent=2),
              file=sys.stderr)


if __name__ == "__main__":
    main()
