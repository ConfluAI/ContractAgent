"""
切分 劳动合同法实施条例 .docx → JSONL chunks + 双向桥接。

与民法典司法解释切分类似，额外提取 cites_labor_contract_law 引用，
构建 实施条例 ↔ 劳动合同法 的桥接文件。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from docx import Document

SOURCE_NAME = "中华人民共和国劳动合同法实施条例"

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


# ── 章节→domain 映射 ─────────────────────────────────────────────────────

CHAPTER_DOMAIN_MAP = {
    1: "劳动合同实施总则",
    2: "劳动合同订立",
    3: "劳动合同解除与终止",
    4: "劳务派遣",
    5: "法律责任",
}

# ── 正则 ─────────────────────────────────────────────────────────────────

CHAPTER_RE = re.compile(r"^第([一二三四五六七八九十]+)章\s+(.+)$")
ARTICLE_RE = re.compile(r"^第([一二三四五六七八九十百千零]+)条\b")


def is_article_start(text: str) -> bool:
    return bool(ARTICLE_RE.match(text))


def parse_chapter(text: str) -> tuple[int, str] | None:
    m = CHAPTER_RE.match(text)
    if not m:
        return None
    return cn_to_int(m.group(1)), m.group(2).strip()


# ── 劳动合同法引用提取 ─────────────────────────────────────────────────

CITE_ARTICLE_RE = re.compile(r"第([一二三四五六七八九十百千零]+)条")


def extract_law_cites(text: str) -> list[int]:
    """从文本中提取对劳动合同法的条文引用。

    仅当"劳动合同法第"出现时触发扫描，排除标题中"劳动合同法》"等非引用场景。
    处理省略式引用：劳动合同法第38条、第46条 → [38, 46]
    """
    nums = []
    for m in re.finditer(r"劳动合同法第", text):
        segment = text[m.start():m.start() + 120]
        for cm in CITE_ARTICLE_RE.finditer(segment):
            num = cn_to_int(cm.group(1))
            if num > 0:
                nums.append(num)
    return sorted(set(nums))


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
    chunks = []
    current_lines: list[str] = []
    current_article_id: str | None = None

    for text in paragraphs[content_start:]:
        ch = parse_chapter(text)
        if ch is not None:
            if current_article_id and current_lines and chapter_num != 6:  # 跳过附则
                chunks.append(_build_chunk(
                    current_article_id, current_lines, chapter_num, chapter_title
                ))
            chapter_num, chapter_title = ch
            current_lines = []
            current_article_id = None
            continue

        if is_article_start(text):
            if current_article_id and current_lines and chapter_num != 6:
                chunks.append(_build_chunk(
                    current_article_id, current_lines, chapter_num, chapter_title
                ))
            m = ARTICLE_RE.match(text)
            current_article_id = m.group()
            current_lines = [text]
        else:
            if current_lines:
                current_lines.append(text)

    if current_article_id and current_lines and chapter_num != 6:
        chunks.append(_build_chunk(
            current_article_id, current_lines, chapter_num, chapter_title
        ))

    return chunks


def _int_to_cn(n: int) -> str:
    MAP = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五",
           6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}
    if n <= 10:
        return MAP.get(n, str(n))
    if n < 20:
        return f"十{MAP.get(n - 10, '')}"
    return str(n)


def _build_chunk(
    article_id: str, lines: list[str],
    chapter_num: int, chapter_title: str,
) -> dict:
    full_text = "\n".join(lines)
    article_num = cn_to_int(ARTICLE_RE.match(article_id).group(1))

    chapter_full = f"第{_int_to_cn(chapter_num)}章 {chapter_title}"

    page_content = f"{SOURCE_NAME}\n{chapter_full}\n{full_text}"

    domain = CHAPTER_DOMAIN_MAP.get(chapter_num, "劳动合同实施通用")

    return {
        "page_content": page_content,
        "metadata": {
            "source": SOURCE_NAME,
            "section_id": article_id,
            "article_num": article_num,
            "chapter": chapter_full,
            "law_rank": 3,
            "law_rank_desc": "行政法规",
            "domain": domain,
        },
    }


# ── Main ────────────────────────────────────────────────────────────────


def main() -> None:
    input_path = Path("data/中华人民共和国劳动合同法实施条例_20080918.docx")
    output_path = Path("data/labor_contract_regulation_chunks.jsonl")
    bridge_path = Path("data/labor_contract_law_bridge.json")

    print(f"Reading {input_path}...", file=sys.stderr)
    chunks = extract_articles(str(input_path))
    print(f"Extracted {len(chunks)} articles.", file=sys.stderr)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    # 构建双向桥接
    law_to_reg: dict[str, list[dict]] = {}
    reg_to_law: dict[str, list[int]] = {}
    total_cites = 0

    for c in chunks:
        cites = extract_law_cites(c["page_content"])
        reg_key = str(c["metadata"]["article_num"])
        if cites:
            reg_to_law[reg_key] = cites
            total_cites += len(cites)
            for num in cites:
                law_key = str(num)
                if law_key not in law_to_reg:
                    law_to_reg[law_key] = []
                law_to_reg[law_key].append({
                    "section_id": c["metadata"]["section_id"],
                    "article_num": c["metadata"]["article_num"],
                    "chapter": c["metadata"]["chapter"],
                })

    bridge = {
        "labor_contract_law_to_regulation": law_to_reg,
        "regulation_to_labor_contract_law": reg_to_law,
    }
    with open(bridge_path, "w", encoding="utf-8") as f:
        json.dump(bridge, f, ensure_ascii=False, indent=2)

    print(f"\nBridge statistics:", file=sys.stderr)
    print(f"  Total citations: {total_cites}", file=sys.stderr)
    print(f"  law -> regulation: {len(law_to_reg)} links", file=sys.stderr)
    print(f"  regulation -> law: {len(reg_to_law)} links", file=sys.stderr)

    from collections import Counter
    ch_counts = Counter(c["metadata"]["chapter"] for c in chunks)
    for ch, cnt in sorted(ch_counts.items()):
        print(f"  {ch}: {cnt} 条", file=sys.stderr)

    print(f"\nDone. Output: {output_path}", file=sys.stderr)
    print(f"Bridge: {bridge_path}", file=sys.stderr)

    if chunks:
        print("\n── Sample ──", file=sys.stderr)
        print(chunks[0]["page_content"][:300], file=sys.stderr)
        print("...", file=sys.stderr)


if __name__ == "__main__":
    main()
