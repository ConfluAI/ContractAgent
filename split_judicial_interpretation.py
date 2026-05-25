"""
最高人民法院民法典合同编通则司法解释 .docx → JSONL chunks。

与民法典切分脚本的核心区别：
  - 额外提取 cites_civil_code 元数据 — 从正文中识别"民法典第X条"引用，
    将其转换为条文号列表，形成司法解释 → 民法典的知识图谱链接。
    后续检索司法解释时可直接关联到民法典原文条文。
"""

import json
import re
import sys
from pathlib import Path
from docx import Document

# ── 章节 → domain 映射 ─────────────────────────────────────────────────

SECTION_DOMAIN_MAP = {
    "一般规定": "合同通则",
    "合同的订立": "合同订立",
    "合同的效力": "合同效力",
    "合同的履行": "合同履行",
    "合同的保全": "合同保全",
    "合同的变更和转让": "合同变更与转让",
    "合同的权利义务终止": "合同终止",
    "违约责任": "违约责任",
    "附则": "合同通用",
}

SOURCE_NAME = "最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释"

# ── 中文数字 → 整数 ────────────────────────────────────────────────────

CN_NUM_MAP = {
    # 基础
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
    "十": 10, "百": 100, "千": 1000,
    "零": 0,
}


def cn_to_int(cn: str) -> int:
    """中文数字字符串 → 整数。如 '五百三十三' → 533, '一百四十二' → 142"""
    if not cn:
        return 0
    result = 0
    seg = 0  # 当前段的累加值（千/百/十以内的部分）
    for ch in cn:
        if ch in ("十", "百", "千"):
            if seg == 0:
                seg = 1  # 如"十" = 一十
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


CN_ARTICLE_RE = re.compile(r"[一二三四五六七八九十百千零]+")


def parse_cn_article_num(text: str) -> int:
    """从'第X条'或'第X条第Y款'中提取条文号整数。"""
    m = CN_ARTICLE_RE.search(text)
    if m:
        return cn_to_int(m.group())
    return 0


# ── 民法典引用提取 ──────────────────────────────────────────────────────

CITE_ARTICLE_RE = re.compile(r"第([一二三四五六七八九十百千零]+)条")


def extract_civil_code_cites(text: str) -> list[int]:
    """从文本中提取所有民法典条文引用，返回去重排序的条文号列表。

    仅当"民法典"后紧跟"第"（即"民法典第"）时触发扫描，
    排除标题中"中华人民共和国民法典》"等非引用场景。
    处理省略式引用：民法典第142条、第466条 → [142, 466]
    """
    nums = []
    for m in re.finditer(r"民法典第", text):
        segment = text[m.start():m.start() + 100]
        for cm in CITE_ARTICLE_RE.finditer(segment):
            num = cn_to_int(cm.group(1))
            if num > 0:
                nums.append(num)
    return sorted(set(nums))


# ── 文章条号识别 ────────────────────────────────────────────────────────

JUDICIAL_ARTICLE_RE = re.compile(r"^第([一二三四五六七八九十百千零]+)条\b")


def is_article_start(text: str) -> bool:
    return bool(JUDICIAL_ARTICLE_RE.match(text))


# ── 章节标题识别 ────────────────────────────────────────────────────────

SECTION_RE = re.compile(r"^([一二三四五六七八九十]+)、(.+)$")


def parse_section(text: str) -> str | None:
    """解析如'一、一般规定' → '一般规定'"""
    m = SECTION_RE.match(text)
    return m.group(2) if m else None


# ── 主提取逻辑 ──────────────────────────────────────────────────────────


def extract_articles(docx_path: str) -> list[dict]:
    doc = Document(docx_path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    # 找到第一个章节标题（确保第一条之前的章节不会丢失）
    start_idx = 0
    for i, text in enumerate(paragraphs):
        if parse_section(text) is not None:
            start_idx = i
            break
    else:
        # 无章节标题，退回到第一条条文开始
        for i, text in enumerate(paragraphs):
            if text.startswith("第") and "条" in text[:6]:
                start_idx = i
                break

    # 先设置第一个章节
    first_sec = parse_section(paragraphs[start_idx])
    current_section = first_sec if first_sec else "一般规定"

    chunks = []
    current_article_lines: list[str] = []
    current_article_id: str | None = None

    for text in paragraphs[start_idx:]:
        # 章节标题检测
        section = parse_section(text)
        if section:
            # 保存前一条
            if current_article_id and current_article_lines:
                chunks.append(
                    _build_chunk(current_article_id, current_article_lines,
                                 current_section))
            current_section = section
            current_article_lines = []
            current_article_id = None
            continue

        # 新条文检测
        if is_article_start(text):
            # 保存前一条
            if current_article_id and current_article_lines:
                chunks.append(
                    _build_chunk(current_article_id, current_article_lines,
                                 current_section))
            current_article_id = JUDICIAL_ARTICLE_RE.match(text).group()
            current_article_lines = [text]
        else:
            # 续行
            if current_article_lines:
                current_article_lines.append(text)

    # 最后一条
    if current_article_id and current_article_lines:
        chunks.append(
            _build_chunk(current_article_id, current_article_lines,
                         current_section))

    return chunks


def _build_chunk(article_id: str, lines: list[str], section: str) -> dict:
    full_text = "\n".join(lines)
    article_num = parse_cn_article_num(article_id)
    domain = SECTION_DOMAIN_MAP.get(section, "合同通用")

    page_content = f"{SOURCE_NAME}\n"
    if section:
        page_content += f"{section}\n"
    page_content += f"{article_id} {lines[0][len(article_id):].lstrip()}"

    if len(lines) > 1:
        for line in lines[1:]:
            page_content += line

    return {
        "page_content": page_content,
        "metadata": {
            "source": SOURCE_NAME,
            "section_id": article_id,
            "article_num": article_num,
            "chapter": section,
            "law_rank": 4,
            "law_rank_desc": "司法解释",
            "domain": domain,
        },
    }


# ── Main ────────────────────────────────────────────────────────────────


def main() -> None:
    input_path = Path("data/最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释_20231204.docx")
    output_path = Path("data/judicial_interpretation_contract_general.jsonl")
    bridge_path = Path("data/contract_law_bridge.json")

    print(f"Reading {input_path}...", file=sys.stderr)
    chunks = extract_articles(str(input_path))
    print(f"Extracted {len(chunks)} articles.", file=sys.stderr)

    # 输出 JSONL（不含 cites_civil_code）
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    # 构建双向桥接文件
    civil_to_interp: dict[str, list[dict]] = {}
    interp_to_civil: dict[str, list[int]] = {}
    total_cites = 0

    for c in chunks:
        cites = extract_civil_code_cites(c["page_content"])
        interp_key = str(c["metadata"]["article_num"])
        if cites:
            interp_to_civil[interp_key] = cites
            total_cites += len(cites)
            for num in cites:
                civil_key = str(num)
                if civil_key not in civil_to_interp:
                    civil_to_interp[civil_key] = []
                civil_to_interp[civil_key].append({
                    "section_id": c["metadata"]["section_id"],
                    "article_num": c["metadata"]["article_num"],
                    "chapter": c["metadata"]["chapter"],
                })

    bridge = {
        "civil_to_interpretation": civil_to_interp,
        "interpretation_to_civil": interp_to_civil,
    }
    with open(bridge_path, "w", encoding="utf-8") as f:
        json.dump(bridge, f, ensure_ascii=False, indent=2)

    print(f"Total citations: {total_cites}", file=sys.stderr)
    print(f"  civil_code -> interpretation: {len(civil_to_interp)} links",
          file=sys.stderr)
    print(f"  interpretation -> civil_code: {len(interp_to_civil)} links",
          file=sys.stderr)
    print(f"Done. Output: {output_path}, Bridge: {bridge_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
