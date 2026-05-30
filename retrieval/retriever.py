"""
合同审查检索管线 — 配置驱动的多分支并行检索。

加新领域 = 在 BRANCH_SPEC 加一条配置，零代码改动。

检索流程:
  1. 调用方指定 branches=["civil", "labor"]
  2. 各分支间并行（ThreadPoolExecutor）
  3. 分支内部多路向量检索并行
  4. 桥接补全 → 向量预截断(Top N) → LLM Rerank
  5. QA 模式可跳过 Rerank，向量排序直接输出
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document

from config.models import get_client, model_name
from retrieval.loaders import load_bridge
from retrieval.embeddings import SiliconFlowEmbeddings

PERSIST_DIR = str(Path(__file__).resolve().parent.parent / "data" / "chroma_civil_code")

# ═══════════════════════════════════════════════════════════════════════════
# 分支规格（配置驱动 — 加新领域只改这里）
# ═══════════════════════════════════════════════════════════════════════════

BRANCH_SPEC: dict[str, dict[str, Any]] = {
    "civil": {
        "priority": 2,
        "label": "合同通用规范",
        "description": "民法典+合同编解释",
        "bridged": [{
            "primary": "civil_code",
            "secondary": "judicial_interpretation",
            "primary_k": 2,
            "secondary_k": 2,
            "bridge_loader": lambda: load_bridge("civil_code"),
            "primary_to_secondary": "civil_to_interpretation",
            "secondary_to_primary": "interpretation_to_civil",
        }],
        "standalone": [],
        "max_rerank_blocks": 5,
    },
    "labor": {
        "priority": 1,
        "label": "劳动法律规范",
        "description": "劳动合同法+实施条例+劳动法，特别法优先适用",
        "bridged": [{
            "primary": "labor_contract_law",
            "secondary": "labor_contract_regulation",
            "primary_k": 2,   # 从 3 降到 2，减少桥接膨胀
            "secondary_k": 2,
            "bridge_loader": lambda: load_bridge("labor_contract_law"),
            "primary_to_secondary": "labor_contract_law_to_regulation",
            "secondary_to_primary": "regulation_to_labor_contract_law",
        }],
        "standalone": [
            {"collection": "labor_law", "k": 1},  # 从 2 降到 1
        ],
        "max_rerank_blocks": 5,
    },
}


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
    """当只有 1 个分支时放大 k 值（唯一依据需要更多候选）。"""
    return 2 if len(active_branches) == 1 else 1


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
# 知识块组装 + 标签
# ═══════════════════════════════════════════════════════════════════════════

def _assemble_block(pair: dict, idx: int) -> str:
    primary = pair["primary"]
    secondary = pair["secondary"]

    parts = [f"【单元 {chr(65 + idx)}】"]

    if primary:
        pid = primary.metadata.get("section_id", "")
        text = primary.page_content
        pos = text.find(pid) if pid else -1
        body = text[pos:] if pos >= 0 else text
        parts.append(f"[{_fmt_source(primary.metadata)}] {body[:400]}")
    else:
        parts.append("（无上位法配对）")

    if secondary:
        sid = secondary.metadata.get("section_id", "")
        stext = secondary.page_content
        pos = stext.find(sid) if sid else -1
        body = stext[pos:] if pos >= 0 else stext
        parts.append(f"[{_fmt_source(secondary.metadata)}] {body[:400]}")

    return "\n".join(parts)


def _derive_tags(primary: Document | None, secondary: Document | None) -> list[str]:
    tags = []
    if primary:
        for field in ("domain", "chapter"):
            val = primary.metadata.get(field, "")
            if val and val not in tags:
                tags.append(val)
    if secondary:
        domain = secondary.metadata.get("domain", "")
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
                    "primary": law_doc,
                    "secondary": sub_by_num.get(snum),
                    "tags": _derive_tags(law_doc, sub_by_num.get(snum)),
                    "_source": "bridged",
                })
        else:
            pairs.append({
                "primary": law_doc,
                "secondary": None,
                "tags": _derive_tags(law_doc, None),
                "_source": "direct",
            })

    used_snums = {p["secondary"].metadata["article_num"] for p in pairs if p["secondary"]}
    for snum, sub_doc in sub_by_num.items():
        if snum not in used_snums:
            pairs.append({
                "primary": None,
                "secondary": sub_doc,
                "tags": _derive_tags(None, sub_doc),
                "_source": "orphan",
            })

    return pairs


def _dedup_pairs(pairs: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for p in pairs:
        cnum = p["primary"].metadata["article_num"] if p["primary"] else None
        inum = p["secondary"].metadata["article_num"] if p["secondary"] else None
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

输出 JSON 数组，按 total 降序排列。只输出 unit/total/verdict，不要输出子分和理由：
[
  {{
    "unit": "A",
    "total": 10,
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
    # 去掉 ```json ... ``` 包裹
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
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


def _vector_sort(pairs: list[dict]) -> list[dict]:
    """向量相似度简易排序：直接命中 > 桥接补全 > 孤儿。无 LLM 调用。"""
    order = {"direct": 0, "bridged": 1, "orphan": 2}
    scored = []
    for p in pairs:
        source = p.pop("_source", "bridged")
        rank = order.get(source, 1)
        # 直接命中给高分，桥接次之
        applicability = 4 if source == "direct" else 3 if source == "bridged" else 2
        scored.append({
            "applicability": applicability,
            "completeness": 3,
            "complementarity": 3 if p["secondary"] else 1,
            "total": applicability + 3 + (3 if p["secondary"] else 1),
            "reason": "向量相似度排序（QA 模式）",
            "verdict": "RELEVANT" if applicability >= 3 else "IRRELEVANT",
            "pair": p,
        })
    scored.sort(key=lambda x: -x["total"])
    return scored


def _build_cache(store: Chroma) -> dict[int, Document]:
    cache = {}
    results = store.get(include=["documents", "metadatas"])
    for i, meta in enumerate(results["metadatas"]):
        doc = Document(page_content=results["documents"][i], metadata=meta)
        cache[meta["article_num"]] = doc
    return cache


# ═══════════════════════════════════════════════════════════════════════════
# 共享组装函数
# ═══════════════════════════════════════════════════════════════════════════

def assemble_branch_results(
    branch_items: dict[str, list[dict]],
    branches: list[str],
) -> dict:
    """按 BRANCH_SPEC priority 组装分支检索结果为 assembled_text。

    供 workflow._merge_retrieval_node 和 ContractRetriever.search() 共用。
    """
    sorted_branches = sorted(
        branches, key=lambda n: BRANCH_SPEC[n]["priority"]
    )
    parts = []
    for name in sorted_branches:
        items = branch_items.get(name, [])
        if not items:
            continue
        spec = BRANCH_SPEC[name]
        parts.append("=" * 60)
        parts.append(f"【第{spec['priority']}优先级：{spec['label']}】")
        parts.append(f"（{spec['description']}）")
        parts.append("=" * 60)
        for r in items:
            if r.get("block_text"):
                parts.append(r["block_text"])
            parts.append(
                f">> 总分={r.get('total','?')} "
                f"| {r.get('verdict','')}"
            )
        parts.append("")

    return {
        **branch_items,
        "activated_branches": branches,
        "assembled_text": "\n".join(parts).strip(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 主检索器
# ═══════════════════════════════════════════════════════════════════════════

class ContractRetriever:
    """配置驱动的多分支并行检索器。

    用法:
      r = ContractRetriever()
      r.search_branch("civil", query)           # 单分支
      r.search(query, branches=["civil", "labor"])  # 多分支并行
    """

    def __init__(self):
        self._embeddings = SiliconFlowEmbeddings()

        self._stores: dict[str, Chroma] = {}
        for col_name in _all_collections():
            self._stores[col_name] = Chroma(
                collection_name=col_name,
                persist_directory=PERSIST_DIR,
                embedding_function=self._embeddings,
            )

        self._bridges: dict[int, dict] = {}
        for spec in BRANCH_SPEC.values():
            for bp in spec.get("bridged", []):
                bridge_id = id(bp["bridge_loader"])
                if bridge_id not in self._bridges:
                    self._bridges[bridge_id] = bp["bridge_loader"]()

        self._cache: dict[str, dict[int, Document]] = {}
        for col_name in _all_collections():
            self._cache[col_name] = _build_cache(self._stores[col_name])

    # ── 单分支检索 ────────────────────────────────────────────────────

    def search_branch(
        self,
        branch_name: str,
        query: str,
        k_multiplier: int = 1,
        rerank: bool = True,
    ) -> list[dict]:
        """执行单个分支的完整检索管线。

        Args:
          branch_name: 分支名 ("civil" / "labor" / ...)
          query: 用户问题
          k_multiplier: 向量召回放大倍数
          rerank: True=LLM Rerank, False=向量排序（QA 模式，快）
        """
        spec = BRANCH_SPEC[branch_name]

        # ── 第 1 步：多路向量检索并行 ──
        search_tasks: dict[str, list[Document]] = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures: dict[Any, str] = {}

            for bp in spec.get("bridged", []):
                pk = bp["primary_k"] * k_multiplier
                sk = bp["secondary_k"] * k_multiplier
                key_pri = f"pri:{bp['primary']}"
                key_sec = f"sec:{bp['secondary']}"
                futures[pool.submit(
                    self._stores[bp["primary"]].similarity_search, query, k=pk
                )] = key_pri
                futures[pool.submit(
                    self._stores[bp["secondary"]].similarity_search, query, k=sk
                )] = key_sec

            for sa in spec.get("standalone", []):
                key_sa = f"sa:{sa['collection']}"
                futures[pool.submit(
                    self._stores[sa["collection"]].similarity_search, query, k=sa["k"]
                )] = key_sa

            for fut in as_completed(futures):
                search_tasks[futures[fut]] = fut.result()

        # ── 第 2 步：桥接补全 ──
        all_pairs: list[dict] = []
        for bp in spec.get("bridged", []):
            pri_key = f"pri:{bp['primary']}"
            sec_key = f"sec:{bp['secondary']}"
            pri_hits = search_tasks.get(pri_key, [])
            sec_hits = search_tasks.get(sec_key, [])
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

        for sa in spec.get("standalone", []):
            for doc in search_tasks.get(f"sa:{sa['collection']}", []):
                all_pairs.append({
                    "primary": doc,
                    "secondary": None,
                    "tags": _derive_tags(doc, None),
                    "_source": "direct",
                })

        all_pairs = _dedup_pairs(all_pairs)

        # ── 第 3 步：预截断（减少送给 LLM 的块数）──
        max_blocks = spec.get("max_rerank_blocks", 6)
        if len(all_pairs) > max_blocks:
            # 直接命中 > 桥接补全 > 孤儿
            order = {"direct": 0, "bridged": 1, "orphan": 2}
            all_pairs.sort(key=lambda p: order.get(p.get("_source", "bridged"), 1))
            all_pairs = all_pairs[:max_blocks]

        # ── 第 4 步：排序（LLM Rerank 或 向量排序）──
        blocks = [_assemble_block(p, i) for i, p in enumerate(all_pairs)]
        # 清理 _source（不给 LLM 看到内部标记）
        for p in all_pairs:
            p.pop("_source", None)

        if rerank:
            scores = _llm_rerank(query, blocks)
            return _merge_scores(scores, all_pairs, blocks)
        else:
            scored = _vector_sort(all_pairs)
            for i, s in enumerate(scored):
                if i < len(blocks):
                    s["block_text"] = blocks[i]
            return scored

    # ── 多分支并行入口 ────────────────────────────────────────────────

    def search(
        self,
        query: str,
        branches: list[str] | None = None,
        top_k: dict[str, int] | None = None,
        rerank: bool = True,
    ) -> dict:
        """多分支并行检索。

        Args:
          query: 用户问题或合同片段
          branches: 激活的分支列表，默认 ["civil"]
          top_k: 分支名 → 保留条数
          rerank: QA 模式可传 False 跳过 LLM Rerank
        """
        if branches is None:
            branches = ["civil"]
        if top_k is None:
            top_k = {b: 5 for b in branches}

        km = _bridged_pair_k_multiplier(branches)

        # ── 分支间并行 ──
        results: dict[str, list[dict]] = {}
        with ThreadPoolExecutor(max_workers=len(branches)) as pool:
            fut_map = {
                pool.submit(self.search_branch, name, query, km, rerank): name
                for name in branches
            }
            for fut in as_completed(fut_map):
                name = fut_map[fut]
                results[name] = fut.result()[: top_k.get(name, 5)]

        # ── 组装 ──
        return assemble_branch_results(results, branches)
