"""
切分 中华人民共和国劳动合同法 .docx → JSONL chunks。

全法均为劳动合同相关，仅排除第八章 附则（实施日期等过渡条款）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from docx import Document

SOURCE_NAME = "中华人民共和国劳动合同法"

# ── 中文数字 → 整数 ──────────────────────────────────────────────────────

CN_NUM_MAP = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
    "十": 10, "百": 100,
    "零": 0,
}


def cn_to_int(cn: str) -> int:
    result = 0
    seg = 0
    for ch in cn:
        if ch in ("十", "百"):
            if seg == 0:
                seg = 1
            seg *= CN_NUM_MAP[ch]
        else:
            if seg >= 10:
                result += seg
                seg = 0
            seg += CN_NUM_MAP.get(ch, 0)
    result += seg
    return result


# ── 章节→domain 映射 ─────────────────────────────────────────────────────

CHAPTER_DOMAIN_MAP = {
    1: "劳动合同总则",
    2: "劳动合同订立",
    3: "劳动合同履行与变更",
    4: "劳动合同解除与终止",
    5: "特别规定",
    6: "监督检查",
    7: "法律责任",
}

# ── 正则 ─────────────────────────────────────────────────────────────────

CHAPTER_RE = re.compile(r"^第([一二三四五六七八九十]+)章\s+(.+)$")
SECTION_RE = re.compile(r"^第([一二三四五六七八九十]+)节\s+(.+)$")
ARTICLE_RE = re.compile(r"^第([一二三四五六七八九十百千零]+)条\b")


def is_article_start(text: str) -> bool:
    return bool(ARTICLE_RE.match(text))


def parse_chapter(text: str) -> tuple[int, str] | None:
    m = CHAPTER_RE.match(text)
    if not m:
        return None
    return cn_to_int(m.group(1)), m.group(2).strip()


def parse_section(text: str) -> str | None:
    m = SECTION_RE.match(text)
    return m.group(2).strip() if m else None


# ── 主提取逻辑 ──────────────────────────────────────────────────────────


def extract_articles(docx_path: str) -> list[dict]:
    doc = Document(docx_path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    # 找到第一条条文，回溯到所在章节标题（不依赖 TOC 偏移量）
    content_start = 0
    for i, text in enumerate(paragraphs):
        if is_article_start(text):
            content_start = i
            break
    while content_start > 0:
        prev = paragraphs[content_start - 1]
        if CHAPTER_RE.match(prev):
            content_start -= 1
            break
        content_start -= 1

    chapter_num = None
    chapter_title = None
    section_title = None
    chunks = []
    current_lines: list[str] = []
    current_article_id: str | None = None

    for text in paragraphs[content_start:]:
        ch = parse_chapter(text)
        if ch is not None:
            _flush(current_article_id, current_lines, chapter_num,
                   chapter_title, section_title, chunks)
            chapter_num, chapter_title = ch
            section_title = None
            current_lines = []
            current_article_id = None
            continue

        sec = parse_section(text)
        if sec is not None:
            section_title = sec
            continue

        if is_article_start(text):
            _flush(current_article_id, current_lines, chapter_num,
                   chapter_title, section_title, chunks)
            m = ARTICLE_RE.match(text)
            current_article_id = m.group()
            current_lines = [text]
        else:
            if current_lines:
                current_lines.append(text)

    _flush(current_article_id, current_lines, chapter_num,
           chapter_title, section_title, chunks)

    return chunks


def _flush(
    article_id: str | None, lines: list[str],
    chapter_num: int | None, chapter_title: str | None,
    section_title: str | None, chunks: list,
) -> None:
    if not article_id or not lines or chapter_num is None:
        return
    if chapter_num == 8:  # 附则，跳过
        return
    chunks.append(_build_chunk(
        article_id, lines, chapter_num, chapter_title, section_title
    ))


def _int_to_cn(n: int) -> str:
    MAP = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五",
           6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}
    return MAP.get(n, str(n))


def _build_chunk(
    article_id: str, lines: list[str],
    chapter_num: int, chapter_title: str,
    section_title: str | None,
) -> dict:
    full_text = "\n".join(lines)
    article_num = cn_to_int(ARTICLE_RE.match(article_id).group(1))

    chapter_full = f"第{_int_to_cn(chapter_num)}章 {chapter_title}"

    page_content = f"{SOURCE_NAME}\n{chapter_full}"
    if section_title:
        page_content += f"\n{section_title}"
    page_content += f"\n{full_text}"

    domain = CHAPTER_DOMAIN_MAP.get(chapter_num, "劳动合同通用")

    meta = {
        "source": SOURCE_NAME,
        "section_id": article_id,
        "article_num": article_num,
        "chapter": chapter_full,
        "law_rank": 4,
        "law_rank_desc": "法律",
        "domain": domain,
    }
    if section_title:
        meta["section"] = section_title

    return {"page_content": page_content, "metadata": meta}


# ── Main ────────────────────────────────────────────────────────────────


def main() -> None:
    input_path = Path("data/中华人民共和国劳动合同法_20121228.docx")
    output_path = Path("data/labor_contract_law_chunks.jsonl")

    print(f"Reading {input_path}...", file=sys.stderr)
    chunks = extract_articles(str(input_path))
    print(f"Extracted {len(chunks)} articles.", file=sys.stderr)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    print(f"Done. Output: {output_path}", file=sys.stderr)

    from collections import Counter
    ch_counts = Counter(c["metadata"]["chapter"] for c in chunks)
    for ch, cnt in sorted(ch_counts.items()):
        print(f"  {ch}: {cnt} 条", file=sys.stderr)

    if chunks:
        print("\n── Sample ──", file=sys.stderr)
        print(chunks[0]["page_content"][:300], file=sys.stderr)
        print("...", file=sys.stderr)


if __name__ == "__main__":
    main()
