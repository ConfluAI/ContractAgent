"""
合同审查检索管线 — 配置驱动的多分支并行检索。

加新领域 = 在 BRANCH_SPEC 加一条配置，零代码改动。

检索流程:
  1. 调用方指定 branches=["civil", "labor"]
  2. 每分支：bridged pairs(向量+桥接) + standalone(独立)
  3. 各分支独立 LLM Rerank
  4. 按优先级降序组装输出
"""

import json
import re
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document

from config.models import get_client, model_name
from utils import load_bridge, load_labor_contract_bridge
from utils.retrieval import SiliconFlowEmbeddings

PERSIST_DIR = str(Path(__file__).resolve().parent / "data" / "chroma_civil_code")

# ═══════════════════════════════════════════════════════════════════════════
# 分支规格（配置驱动 — 加新领域只改这里）
# ═══════════════════════════════════════════════════════════════════════════

BRANCH_SPEC: dict[str, dict[str, Any]] = {
    "civil": {
        "priority": 2,                    # 1=最高优，数字越小越靠前
        "label": "合同通用规范",
        "description": "民法典+合同编解释",
        "bridged": [{
            "primary": "civil_code",
            "secondary": "judicial_interpretation",
            "primary_k": 2,
            "secondary_k": 2,
            "bridge_loader": lambda: load_bridge(),
            "primary_to_secondary": "civil_to_interpretation",
            "secondary_to_primary": "interpretation_to_civil",
        }],
        "standalone": [],
    },
    "labor": {
        "priority": 1,
        "label": "劳动法律规范",
        "description": "劳动合同法+实施条例+劳动法，特别法优先适用",
        "bridged": [{
            "primary": "labor_contract_law",
            "secondary": "labor_contract_regulation",
            "primary_k": 3,
            "secondary_k": 3,
            "bridge_loader": lambda: load_labor_contract_bridge(),
            "primary_to_secondary": "labor_contract_law_to_regulation",
            "secondary_to_primary": "regulation_to_labor_contract_law",
        }],
        "standalone": [
            {"collection": "labor_law", "k": 2},
        ],
    },
}

# 从 spec 中提取所有 collection 名称
def _all_collections() -> list[str]:
    cols = set()
    for spec in BRANCH_SPEC.values():
        for bp in spec.get("bridged", []):
            cols.add(bp["primary"])
            cols.add(bp["secondary"])
        for sa in spec.get("standalone", []):
            cols.add(sa["collection"])
    return sorted(cols)


def _bridged_pair_k_multiplier(active_branches: list[str]) -> int:
    """民事分支独立使用时放大 k 值（它是唯一依据）。"""
    return 2 if active_branches == ["civil"] else 1


# ═══════════════════════════════════════════════════════════════════════════
# 出处格式化
# ═══════════════════════════════════════════════════════════════════════════

def _fmt_source(meta: dict) -> str:
    source = meta.get("source", "")
    short = source.replace(
        "最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释",
        "合同编通则解释",
    )
    parts = [short]
    for key in ("book", "chapter", "section"):
        val = meta.get(key, "")
        if val:
            parts.append(val)
    return " · ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# 知识块组装
# ═══════════════════════════════════════════════════════════════════════════

def _assemble_block(pair: dict, idx: int) -> str:
    civil = pair["civil"]
    interp = pair["interp"]
    tags = pair.get("tags", [])

    lines = [f"【知识单元 {chr(65 + idx)}】"]

    if civil:
        lines.append("┌─ 出处 ─────────────────────────────────────────────")
        lines.append(f"│ {_fmt_source(civil.metadata)}")
        lines.append(f"│ law_rank: {civil.metadata.get('law_rank_desc', '')}")
        lines.append("├─ 原文 ─────────────────────────────────────────────")
        cid = civil.metadata.get("section_id", "")
        text = civil.page_content
        pos = text.find(cid) if cid else -1
        if pos >= 0:
            text = text[pos:]
        lines.append(f"│ {text[:500]}")
    else:
        lines.append("├─ 原文 ─────────────────────────────────────────────")
        lines.append("│ （无匹配上位法条文）")

    if interp:
        lines.append("├─ 下位法 ───────────────────────────────────────────")
        lines.append(f"│ {_fmt_source(interp.metadata)}")
        lines.append(f"│ law_rank: {interp.metadata.get('law_rank_desc', '')}")
        iid = interp.metadata.get("section_id", "")
        itext = interp.page_content
        pos = itext.find(iid) if iid else -1
        if pos >= 0:
            itext = itext[pos:]
        lines.append(f"│ {itext[:500]}")

    if tags:
        lines.append("├─ 关联标签 ─────────────────────────────────────────")
        lines.append(f"│ {' / '.join(tags)}")

    lines.append("└────────────────────────────────────────────────────")
    return "\n".join(lines)


def _derive_tags(civil: Document | None, interp: Document | None) -> list[str]:
    tags = []
    if civil:
        for field in ("domain", "chapter"):
            val = civil.metadata.get(field, "")
            if val and val not in tags:
                tags.append(val)
    if interp:
        domain = interp.metadata.get("domain", "")
        if domain and domain not in tags:
            tags.append(domain)
    return tags


# ═══════════════════════════════════════════════════════════════════════════
# 桥接补全（通用）
# ═══════════════════════════════════════════════════════════════════════════

def _bridge_completion(
    law_hits: list[Document],
    sub_hits: list[Document],
    bridge: dict,
    law_to_sub_key: str,
    sub_to_law_key: str,
    law_cache: dict[int, Document],
    sub_cache: dict[int, Document],
) -> list[dict]:
    l2s = bridge[law_to_sub_key]
    s2l = bridge[sub_to_law_key]

    law_by_num: dict[int, Document] = {}
    sub_by_num: dict[int, Document] = {}

    for doc in law_hits:
        law_by_num[doc.metadata["article_num"]] = doc
    for doc in sub_hits:
        sub_by_num[doc.metadata["article_num"]] = doc

    # 1-hop: sub → law
    for snum in list(sub_by_num.keys()):
        for lnum in s2l.get(str(snum), []):
            if lnum not in law_by_num:
                doc = law_cache.get(lnum)
                if doc:
                    law_by_num[lnum] = doc

    # 1-hop: law → sub
    for lnum in list(law_by_num.keys()):
        for ref in l2s.get(str(lnum), []):
            snum = ref["article_num"]
            if snum not in sub_by_num:
                doc = sub_cache.get(snum)
                if doc:
                    sub_by_num[snum] = doc

    pairs: list[dict] = []
    for lnum, law_doc in law_by_num.items():
        sub_nums = [r["article_num"] for r in l2s.get(str(lnum), [])]
        if sub_nums:
            for snum in sub_nums:
                pairs.append({
                    "civil": law_doc,
                    "interp": sub_by_num.get(snum),
                    "tags": _derive_tags(law_doc, sub_by_num.get(snum)),
                })
        else:
            pairs.append({
                "civil": law_doc,
                "interp": None,
                "tags": _derive_tags(law_doc, None),
            })

    used_snums = {p["interp"].metadata["article_num"] for p in pairs if p["interp"]}
    for snum, sub_doc in sub_by_num.items():
        if snum not in used_snums:
            pairs.append({
                "civil": None,
                "interp": sub_doc,
                "tags": _derive_tags(None, sub_doc),
            })

    return pairs


def _dedup_pairs(pairs: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for p in pairs:
        cnum = p["civil"].metadata["article_num"] if p["civil"] else None
        inum = p["interp"].metadata["article_num"] if p["interp"] else None
        key = (cnum, inum)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


# ═══════════════════════════════════════════════════════════════════════════
# LLM 重排序
# ═══════════════════════════════════════════════════════════════════════════

RERANK_PROMPT = """你是一位资深法官助理。请从以下法条-解释知识单元中，筛选并排序与审查问题最相关的条目。

审查问题：{query}

评分规则（严格区分，避免分数扎堆）：

适用性 (1-5):
  5 = 条文直接规定了问题的核心法律要件
  4 = 条文与问题高度相关，但并非核心条款
  3 = 条文在适用范围内，但需要推理才能关联
  2 = 条文主题相关，但并非解决该问题的直接依据
  1 = 条文与问题无关或仅字面沾边

完整性 (1-5):
  5 = 法条+解释提供了可直接操作的审查步骤/标准
  4 = 提供了较充分的依据，但缺少部分细节
  3 = 提供了原则性依据，需结合其他条文才能操作
  2 = 仅提供了概念性参考
  1 = 无法作为审查依据

互补性 (1-5):
  5 = 解释精确补充了法条中未明确的审查要点
  3 = 解释与法条有关联但未形成有效补充
  1 = 无解释配对（孤儿），或解释与法条无实质互补

每个单元的 total 应为 applicability+completeness+complementarity 之和。
各单元之间总分应有明显梯度，不得出现 3 个以上单元同分。

独立条文（无配对解释/条例的单行法条）：
- 互补性固定为 1（因为没有下位法配对）
- 此类条文的判定核心是适用性：它是否直接规定了问题的法律要件。
  互补性低是结构原因，不是条文质量差，不应因此压低 total 排名。
- 若适用性 >= 4，应标记 RELEVANT 并给较高的 total（建议 8-12）
- 若适用性 <= 3，标记 IRRELEVANT
- 特别注意：独立条文（如劳动法、劳动合同法）与有配对的条文平等竞争，
  不能因为缺少解释而系统性排在后面

输出 JSON 数组，按 total 降序排列，不要输出其他内容：
[
  {{
    "unit": "A",
    "applicability": 5,
    "completeness": 4,
    "complementarity": 1,
    "total": 10,
    "reason": "直接规定违约金调整标准，但无解释补充审查细节",
    "verdict": "RELEVANT"
  }}
]

{knowledge_blocks}"""


def _llm_rerank(query: str, blocks: list[str]) -> list[dict]:
    client = get_client()
    model = model_name("review_llm")
    blocks_text = "\n\n".join(blocks)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "你是一位资深法官助理。只输出 JSON 数组，不要输出其他内容。",
            },
            {
                "role": "user",
                "content": RERANK_PROMPT.format(
                    query=query, knowledge_blocks=blocks_text
                ),
            },
        ],
        temperature=0,
    )

    raw = resp.choices[0].message.content.strip()
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        raise ValueError(f"LLM 未返回 JSON 数组: {raw[:200]}")
    return json.loads(match.group())


def _merge_scores(
    scores: list[dict], pairs: list[dict], blocks: list[str]
) -> list[dict]:
    merged = []
    for s in scores:
        idx = ord(s["unit"]) - 65
        if 0 <= idx < len(pairs):
            merged.append({**s, "pair": pairs[idx], "block_text": blocks[idx]})
    merged.sort(key=lambda x: -x["total"])
    return merged


def _build_cache(store: Chroma) -> dict[int, Document]:
    cache = {}
    results = store.get(include=["documents", "metadatas"])
    for i, meta in enumerate(results["metadatas"]):
        doc = Document(page_content=results["documents"][i], metadata=meta)
        cache[meta["article_num"]] = doc
    return cache


# ═══════════════════════════════════════════════════════════════════════════
# 主检索器
# ═══════════════════════════════════════════════════════════════════════════

class ContractRetriever:
    """配置驱动的多分支并行检索器。

    用法:
      r = ContractRetriever()
      result = r.search("公司拖欠工资...", branches=["labor", "civil"])
      result = r.search("买方拒付货款...", branches=["civil"])
    """

    def __init__(self):
        self._embeddings = SiliconFlowEmbeddings()

        # ── 从 spec 自动初始化 stores ──
        self._stores: dict[str, Chroma] = {}
        for col_name in _all_collections():
            self._stores[col_name] = Chroma(
                collection_name=col_name,
                persist_directory=PERSIST_DIR,
                embedding_function=self._embeddings,
            )

        # ── 自动初始化桥接（de-dup by id）──
        self._bridges: dict[int, dict] = {}
        for spec in BRANCH_SPEC.values():
            for bp in spec.get("bridged", []):
                bridge_id = id(bp["bridge_loader"])
                if bridge_id not in self._bridges:
                    self._bridges[bridge_id] = bp["bridge_loader"]()

        # ── 自动初始化缓存 ──
        self._cache: dict[str, dict[int, Document]] = {}
        for col_name in _all_collections():
            self._cache[col_name] = _build_cache(self._stores[col_name])

    # ── 单分支检索 ────────────────────────────────────────────────────

    def _search_branch(
        self, branch_name: str, query: str, k_multiplier: int = 1
    ) -> list[dict]:
        """根据 spec 执行单个分支的完整检索管线。"""
        spec = BRANCH_SPEC[branch_name]
        all_pairs: list[dict] = []

        # 桥接对
        for bp in spec.get("bridged", []):
            primary_k = bp["primary_k"] * k_multiplier
            secondary_k = bp["secondary_k"] * k_multiplier
            pri_hits = self._stores[bp["primary"]].similarity_search(query, k=primary_k)
            sec_hits = self._stores[bp["secondary"]].similarity_search(query, k=secondary_k)

            bridge = self._bridges[id(bp["bridge_loader"])]
            pairs = _bridge_completion(
                pri_hits, sec_hits,
                bridge,
                bp["primary_to_secondary"],
                bp["secondary_to_primary"],
                self._cache[bp["primary"]],
                self._cache[bp["secondary"]],
            )
            all_pairs.extend(pairs)

        # 独立库
        for sa in spec.get("standalone", []):
            hits = self._stores[sa["collection"]].similarity_search(query, k=sa["k"])
            for doc in hits:
                all_pairs.append({
                    "civil": doc,
                    "interp": None,
                    "tags": _derive_tags(doc, None),
                })

        all_pairs = _dedup_pairs(all_pairs)
        blocks = [_assemble_block(p, i) for i, p in enumerate(all_pairs)]
        scores = _llm_rerank(query, blocks)
        return _merge_scores(scores, all_pairs, blocks)

    # ── 主入口 ────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        branches: list[str] | None = None,
        top_k: dict[str, int] | None = None,
    ) -> dict:
        """执行多分支检索，返回分区组装结果。

        Args:
          query: 用户问题或合同片段
          branches: 激活的分支列表，默认 ["civil"]。
                    例: ["civil"] / ["civil", "labor"]
          top_k: 分支名 → 保留条数，默认 {"civil": 3, "labor": 5}

        Returns:
          { "<branch_name>": [...], "activated_branches": [...], "assembled_text": str }
        """
        if branches is None:
            branches = ["civil"]
        if top_k is None:
            top_k = {"civil": 3, "labor": 5}

        km = _bridged_pair_k_multiplier(branches)

        # 执行各分支
        results: dict[str, list[dict]] = {}
        for name in branches:
            results[name] = self._search_branch(name, query, k_multiplier=km)[
                : top_k.get(name, 5)
            ]

        # 按 priority 降序组装
        sorted_branches = sorted(branches, key=lambda n: BRANCH_SPEC[n]["priority"])
        parts = []
        for name in sorted_branches:
            items = results[name]
            if not items:
                continue
            spec = BRANCH_SPEC[name]
            parts.append("=" * 60)
            parts.append(f"【第{spec['priority']}优先级：{spec['label']}】")
            parts.append(f"（{spec['description']}）")
            parts.append("=" * 60)
            for r in items:
                parts.append(r["block_text"])
                parts.append(
                    f">> 评分: 适用性={r['applicability']} "
                    f"完整性={r['completeness']} "
                    f"互补性={r['complementarity']} "
                    f"总分={r['total']} | {r['reason']}"
                )
            parts.append("")

        return {
            **results,
            "activated_branches": branches,
            "assembled_text": "\n".join(parts).strip(),
        }
