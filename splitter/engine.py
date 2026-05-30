"""
通用 .docx → JSONL 法律条文切分引擎。

所有法律文档的切分流程完全一致，差异仅在于标题层级和过滤规则。
通过 SplitterConfig 描述每个文档的特征，DocxSplitter 执行统一管线。

用法：
  from splitter.engine import DocxSplitter, SplitterConfig
  DocxSplitter(my_config).run()

新增法律文档只需写一份 SplitterConfig，不需修改引擎代码。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from docx import Document

# ═══════════════════════════════════════════════════════════════════════════
# 中文数字工具（所有切分共用）
# ═══════════════════════════════════════════════════════════════════════════

CN_NUM_MAP = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
    "十": 10, "百": 100, "千": 1000, "万": 10000,
    "零": 0,
}

_INT_TO_CN_SHORT = {
    1: "一", 2: "二", 3: "三", 4: "四", 5: "五",
    6: "六", 7: "七", 8: "八", 9: "九", 10: "十",
    11: "十一", 12: "十二",
}


def cn_to_int(cn: str) -> int:
    """中文数字字符串 → 整数。如 '五百三十三' → 533"""
    if not cn:
        return 0
    result = 0
    seg = 0
    for ch in cn:
        if ch in ("十", "百", "千", "万"):
            if seg == 0:
                seg = 1
            seg *= CN_NUM_MAP[ch]
            if ch in ("千", "万"):
                result += seg
                seg = 0
        else:
            if seg >= 10:
                result += seg
                seg = 0
            seg += CN_NUM_MAP.get(ch, 0)
    result += seg
    return result


def int_to_cn_short(n: int) -> str:
    """整数 → 中文数字（短表，1-99）。"""
    if n <= 12:
        return _INT_TO_CN_SHORT.get(n, str(n))
    if n < 20:
        return f"十{_INT_TO_CN_SHORT.get(n - 10, '')}"
    tens = n // 10
    ones = n % 10
    prefix = _INT_TO_CN_SHORT.get(tens, str(tens))
    if ones == 0:
        return f"{prefix}十"
    return f"{prefix}十{_INT_TO_CN_SHORT.get(ones, '')}"


# ═══════════════════════════════════════════════════════════════════════════
# 配置数据类
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class HeadingLevel:
    """文档中的一个标题层级。

    key:      上下文键名（"book" / "chapter" / "section" …）
    label:    中文标签（"编" / "章" / "节" / "分编" …）
    pattern:  正则字符串，至少包含两组捕获：
              group(1) = 中文数字编号, group(2) = 标题文本
    """
    key: str
    label: str
    pattern: str

    def build_re(self) -> re.Pattern:
        return re.compile(self.pattern)


@dataclass
class BridgeSpec:
    """引用 → 桥接配置。

    cite_trigger:  触发文本（如 "民法典第"），用于定位引用片段
    output_path:   桥接 JSON 输出路径
    key_to_primary:    从属→主法的键名（如 "regulation_to_labor_contract_law"）
    key_from_primary:  主法→从属的键名（如 "labor_contract_law_to_regulation"）
    """
    cite_trigger: str
    output_path: str
    key_to_primary: str
    key_from_primary: str


@dataclass
class SplitterConfig:
    """描述一份法律文档的一切切分参数。"""
    input_path: str
    output_path: str
    source_name: str
    law_rank: int
    law_rank_desc: str
    heading_levels: list[HeadingLevel]

    # 过滤：哪些条文要保留
    include_check: Callable[[dict], bool] = lambda ctx: True
    # 可直接设 exclude_chapters 替代自定义 include_check
    exclude_chapters: set[int] = field(default_factory=set)

    # domain 分类
    domain_map: dict[int, str] = field(default_factory=dict)
    domain_fn: Callable[[dict], str] | None = None  # 复杂逻辑走这儿

    # 桥接（可选）
    bridge: BridgeSpec | None = None

    # 内容起点策略
    # "first_article": 找到第一条"第X条"作为起点，回溯到最近的标题
    content_start_strategy: str = "first_article"


# ═══════════════════════════════════════════════════════════════════════════
# 通用切分引擎
# ═══════════════════════════════════════════════════════════════════════════

class DocxSplitter:
    """法律文档 → JSONL 切分引擎。"""

    def __init__(self, config: SplitterConfig):
        self.cfg = config
        # 预编译所有标题正则
        self._heading_res: list[tuple[HeadingLevel, re.Pattern]] = [
            (hl, hl.build_re()) for hl in config.heading_levels
        ]
        # 条文正则（所有文档通用）
        self._article_re = re.compile(
            r"^第([一二三四五六七八九十百千零]+)条[\s]*"
        )

    # ── 公开入口 ──────────────────────────────────────────────────────

    def run(self) -> list[dict]:
        """执行完整切分管线，返回 chunks 列表（同时写入 JSONL）。"""
        doc = Document(self.cfg.input_path)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

        chunks = self._extract_articles(paragraphs)

        # 写 JSONL
        Path(self.cfg.output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.cfg.output_path, "w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

        # 可选桥接
        if self.cfg.bridge:
            self._build_bridge(chunks)

        self._print_stats(chunks)
        return chunks

    # ── 正文起点定位 ──────────────────────────────────────────────────

    def _find_content_start(self, paragraphs: list[str]) -> int:
        """定位正文第一条条文所在位置，跳过目录/前言。"""
        # 找到第一条条文
        for i, text in enumerate(paragraphs):
            if self._article_re.match(text):
                start = i
                break
        else:
            return 0

        # 回溯到所在章节标题
        while start > 0:
            prev = paragraphs[start - 1]
            if any(hl_re.match(prev) for _, hl_re in self._heading_res):
                start -= 1
                break
            if prev == "":
                start -= 1
            else:
                break

        return start

    # ── 标题解析 ──────────────────────────────────────────────────────

    def _parse_heading(self, text: str) -> tuple[str, dict] | None:
        """尝试匹配标题。返回 (level_key, context_update) 或 None。"""
        for hl, hl_re in self._heading_res:
            m = hl_re.match(text)
            if m:
                num = cn_to_int(m.group(1)) if m.lastindex >= 1 else None
                title = m.group(2).strip() if m.lastindex >= 2 else ""
                # 构建前缀行（如 "第X章 劳动合同"，或仅标题名）
                if hl.label:
                    prefix = f"第{m.group(1)}{hl.label} {title}"
                else:
                    prefix = title
                return hl.key, {
                    f"{hl.key}": title,
                    f"{hl.key}_num": num,
                    f"{hl.key}_prefix": prefix,
                }
        return None

    # ── 条文提取主循环 ────────────────────────────────────────────────

    def _extract_articles(self, paragraphs: list[str]) -> list[dict]:
        """遍历段落，追踪标题上下文，提取条文。"""
        content_start = self._find_content_start(paragraphs)

        # 正文之前的段落可能包含标题（民法典结构深），往前扫收录
        heading_start = content_start
        while heading_start > 0:
            prev = paragraphs[heading_start - 1]
            if self._parse_heading(prev) or prev == "":
                heading_start -= 1
            else:
                break

        # 标题上下文栈（按 heading_levels 顺序）
        ctx: dict = {}
        for hl in self.cfg.heading_levels:
            ctx[hl.key] = None
            ctx[f"{hl.key}_num"] = None
            ctx[f"{hl.key}_prefix"] = None

        chunks: list[dict] = []
        current_id: str | None = None
        current_lines: list[str] = []

        def _flush():
            nonlocal current_id, current_lines
            if current_id and current_lines:
                if self.cfg.include_check(ctx):
                    chunks.append(self._build_chunk(current_id, current_lines, ctx))
            current_id = None
            current_lines = []

        for i, text in enumerate(paragraphs[heading_start:]):
            # 标题
            heading = self._parse_heading(text)
            if heading:
                _flush()
                lvl_key, update = heading
                # 清除该层级及以下所有层级
                found = False
                for hl in self.cfg.heading_levels:
                    if found:
                        ctx[hl.key] = None
                        ctx[f"{hl.key}_num"] = None
                        ctx[f"{hl.key}_prefix"] = None
                    if hl.key == lvl_key:
                        found = True
                ctx.update(update)
                continue

            # 新条文
            art_match = self._article_re.match(text)
            if art_match:
                _flush()
                current_id = art_match.group()  # "第X条"
                body = self._article_re.sub("", text).strip()
                current_lines = [body] if body else []
                continue

            # 跳过正文前的杂项
            if i < (content_start - heading_start):
                continue

            # 续行
            if current_lines:
                current_lines.append(text)

        _flush()
        return chunks

    # ── 知识块构建 ────────────────────────────────────────────────────

    def _build_chunk(
        self, article_id: str, lines: list[str], ctx: dict
    ) -> dict:
        """组装 page_content + metadata。"""
        body = "".join(lines)
        article_cn = self._article_re.match(article_id).group(1)
        article_num = cn_to_int(article_cn)

        # page_content: source + 层级前缀 + 条文
        parts = [self.cfg.source_name]
        for hl in self.cfg.heading_levels:
            prefix = ctx.get(f"{hl.key}_prefix")
            if prefix:
                parts.append(prefix)
        parts.append(f"第{article_cn}条 {body}")
        page_content = "\n".join(parts)

        # metadata
        meta = {
            "source": self.cfg.source_name,
            "section_id": article_id,
            "article_num": article_num,
            "law_rank": self.cfg.law_rank,
            "law_rank_desc": self.cfg.law_rank_desc,
            "domain": self._get_domain(ctx),
        }
        # 填入各层级标题
        for hl in self.cfg.heading_levels:
            prefix = ctx.get(f"{hl.key}_prefix")
            if prefix:
                meta[hl.key] = prefix

        return {"page_content": page_content, "metadata": meta}

    # ── domain 分类 ───────────────────────────────────────────────────

    def _get_domain(self, ctx: dict) -> str:
        """根据上下文推断领域标签。"""
        if self.cfg.domain_fn:
            return self.cfg.domain_fn(ctx)
        # 按 chapter_num 查映射
        cn = ctx.get("chapter_num")
        if cn is not None and self.cfg.domain_map:
            return self.cfg.domain_map.get(cn, f"{self.cfg.source_name}通用")
        return f"{self.cfg.source_name}通用"

    # ── 引用提取 & 桥接 ───────────────────────────────────────────────

    _CITE_ARTICLE_RE = re.compile(r"第([一二三四五六七八九十百千零]+)条")

    def _extract_cites(self, text: str) -> list[int]:
        """从文本中提取主法条文引用编号。"""
        trigger = self.cfg.bridge.cite_trigger
        nums: list[int] = []
        for m in re.finditer(re.escape(trigger), text):
            segment = text[m.start():m.start() + 120]
            for cm in self._CITE_ARTICLE_RE.finditer(segment):
                num = cn_to_int(cm.group(1))
                if num > 0:
                    nums.append(num)
        return sorted(set(nums))

    def _build_bridge(self, chunks: list[dict]) -> None:
        """构建主法 ↔ 从属法的双向桥接 JSON。"""
        bspec = self.cfg.bridge
        to_primary: dict[str, list[int]] = {}
        from_primary: dict[str, list[dict]] = {}
        total = 0

        for c in chunks:
            cites = self._extract_cites(c["page_content"])
            if not cites:
                continue
            sec_key = str(c["metadata"]["article_num"])
            to_primary[sec_key] = cites
            total += len(cites)
            for num in cites:
                pk = str(num)
                if pk not in from_primary:
                    from_primary[pk] = []
                from_primary[pk].append({
                    "section_id": c["metadata"]["section_id"],
                    "article_num": c["metadata"]["article_num"],
                    "chapter": c["metadata"].get("chapter", ""),
                })

        bridge = {
            bspec.key_from_primary: from_primary,
            bspec.key_to_primary: to_primary,
        }
        Path(bspec.output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(bspec.output_path, "w", encoding="utf-8") as f:
            json.dump(bridge, f, ensure_ascii=False, indent=2)

        print(f"Bridge: {total} citations → {bspec.output_path}", file=sys.stderr)

    # ── 统计 ──────────────────────────────────────────────────────────

    def _print_stats(self, chunks: list[dict]) -> None:
        print(f"✓ {self.cfg.source_name}: {len(chunks)} 条", file=sys.stderr)
        from collections import Counter
        if chunks:
            ch_counts = Counter(
                c["metadata"].get("chapter", c["metadata"].get("book", "—"))
                for c in chunks
            )
            for ch, cnt in sorted(ch_counts.items()):
                print(f"    {ch}: {cnt} 条", file=sys.stderr)
            # 抽样
            print("\n── Sample ──", file=sys.stderr)
            print(chunks[0]["page_content"][:300], file=sys.stderr)
            print("...", file=sys.stderr)
            print(json.dumps(chunks[0]["metadata"], ensure_ascii=False, indent=2),
                  file=sys.stderr)
        print(file=sys.stderr)
