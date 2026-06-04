"""
合同审查检索管线 — 配置驱动的多分支并行检索。

加新领域 = 在 BRANCH_SPEC 加一条配置，零代码改动。

检索流程:
  1. 调用方指定 branches=["civil", "labor"]
  2. 各分支间并行（ThreadPoolExecutor）
  3. 分支内部多路向量检索并行
  4. 桥接补全 → BGE Rerank（专用 cross-encoder，~100ms）
  5. QA 模式可跳过 Rerank，来源优先级排序直接输出
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document

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
        # 法条原文必须完整保留，不能截断
        parts.append(f"[{_fmt_source(primary.metadata)}] {body}")
    else:
        parts.append("（无上位法配对）")

    if secondary:
        sid = secondary.metadata.get("section_id", "")
        stext = secondary.page_content
        pos = stext.find(sid) if sid else -1
        body = stext[pos:] if pos >= 0 else stext
        # 法条原文必须完整保留，不能截断
        parts.append(f"[{_fmt_source(secondary.metadata)}] {body}")

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
# BGE 专用重排序（替换 LLM Rerank，延迟 ~100ms）
# ═══════════════════════════════════════════════════════════════════════════


def _bge_rerank(
    query: str,
    blocks: list[str],
    pairs: list[dict],
    top_n: int | None = None,
    threshold: float = 0.5,
) -> list[dict]:
    """BGE-Reranker cross-encoder 重排序。

    所有候选送进 reranker（不再预截断），按 relevance_score 降序返回。
    relevance_score < threshold 的被过滤（BGE 能区分 0.02 vs 0.95，
    低分对应明显不相关的条文，不应送给下游 LLM）。
    桥接保证知识块完整，reranker 保证排序精准——
    各司其职，不需要 LLM 做三维打分。
    """
    from config.models import rerank as call_rerank

    scores = call_rerank(query, blocks, top_n=top_n)

    merged = []
    for s in scores:
        idx = s["index"]
        if 0 <= idx < len(pairs) and s["relevance_score"] >= threshold:
            merged.append({
                "relevance_score": s["relevance_score"],
                "total": round(s["relevance_score"], 3),
                "verdict": "RELEVANT",
                "pair": pairs[idx],
                "block_text": blocks[idx],
            })
        elif 0 <= idx < len(pairs):
            merged.append({
                "relevance_score": s["relevance_score"],
                "total": round(s["relevance_score"], 3),
                "verdict": "IRRELEVANT",
                "pair": pairs[idx],
                "block_text": blocks[idx],
            })

    # 兜底：全被过滤时保留最高分的 1 条，避免下游空白
    if not any(m["verdict"] == "RELEVANT" for m in merged) and scores:
        best = scores[0]
        idx = best["index"]
        if 0 <= idx < len(pairs):
            merged.append({
                "relevance_score": best["relevance_score"],
                "total": round(best["relevance_score"], 3),
                "verdict": "RELEVANT",
                "pair": pairs[idx],
                "block_text": blocks[idx],
            })

    # 只返回 RELEVANT，按分数降序（IRRELEVANT 不送下游）
    relevant = [m for m in merged if m["verdict"] == "RELEVANT"]
    relevant.sort(key=lambda x: -x["total"])
    return relevant


def _simple_sort(pairs: list[dict], blocks: list[str]) -> list[dict]:
    """无 Rerank 时的简易排序：直接命中 > 桥接补全 > 孤儿。"""
    order = {"direct": 0, "bridged": 1, "orphan": 2}
    results = []
    for i, p in enumerate(pairs):
        source = p.get("_source", "bridged")
        rank = order.get(source, 1)
        results.append({
            "relevance_score": 0.0,
            "total": 10 - rank * 3,  # direct=10, bridged=7, orphan=4
            "verdict": "RELEVANT",
            "pair": p,
            "block_text": blocks[i] if i < len(blocks) else "",
        })
    results.sort(key=lambda x: -x["total"])
    return results


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
          rerank: True=BGE Rerank, False=来源优先级排序（QA 模式，快）
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

        # ── 第 3 步：排序（BGE Rerank 或 来源优先级排序）──
        blocks = [_assemble_block(p, i) for i, p in enumerate(all_pairs)]

        if rerank and blocks:
            # BGE Rerank：所有候选送进 cross-encoder，按 relevance_score 降序返回
            # 不再预截断 — reranker 本身高效，候选越多排序越准
            results = _bge_rerank(
                query, blocks, all_pairs,
                top_n=spec.get("max_rerank_blocks", 5),
            )
        elif rerank:
            results = []  # 无候选
        else:
            results = _simple_sort(all_pairs, blocks)

        # 清理内部标记
        for p in all_pairs:
            p.pop("_source", None)

        return results

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
          rerank: QA 模式可传 False 跳过 Rerank
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
