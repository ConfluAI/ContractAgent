"""
JSONL + 桥接文件加载器 — 加载拆分好的法律条文为 Document 对象。

新增法律文档只需在 COLLECTION_SOURCES 加一条记录，load_collection() 自动可用。
"""

from __future__ import annotations

import json
from pathlib import Path
from langchain_core.documents import Document

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"

# ── 集合注册表（新增文档只加这里）─────────────────────────────────────

COLLECTION_SOURCES = {
    "civil_code": {
        "jsonl": "civil_code_contract_chunks.jsonl",
        "label": "民法典",
    },
    "judicial_interpretation": {
        "jsonl": "judicial_interpretation_contract_general.jsonl",
        "label": "司法解释",
    },
    "labor_law": {
        "jsonl": "labor_law_contract_chunks.jsonl",
        "label": "劳动法",
    },
    "labor_contract_law": {
        "jsonl": "labor_contract_law_chunks.jsonl",
        "label": "劳动合同法",
    },
    "labor_contract_regulation": {
        "jsonl": "labor_contract_regulation_chunks.jsonl",
        "label": "实施条例",
    },
}

# 桥接注册表（可选，有引用提取的文档才注册）
BRIDGE_SOURCES = {
    "civil_code": "contract_law_bridge.json",
    "labor_contract_law": "labor_contract_law_bridge.json",
}

# ── 通用加载函数 ─────────────────────────────────────────────────────

def _load_jsonl(path: str) -> list[Document]:
    docs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            chunk = json.loads(line)
            doc = Document(
                page_content=chunk["page_content"],
                metadata=chunk["metadata"],
            )
            docs.append(doc)
    return docs


def load_collection(name: str) -> list[Document]:
    """按集合名加载 JSONL → Document 列表。"""
    spec = COLLECTION_SOURCES[name]
    return _load_jsonl(str(_DATA_DIR / spec["jsonl"]))


def load_bridge(name: str) -> dict:
    """加载指定集合的桥接文件。"""
    bridge_path = BRIDGE_SOURCES[name]
    with open(str(_DATA_DIR / bridge_path), "r", encoding="utf-8") as f:
        return json.load(f)


# ── 向后兼容别名 ──────────────────────────────────────────────────────

def load_chunks() -> list[Document]:
    return load_collection("civil_code")


def load_chunks_by_domain(domain: str | None = None) -> list[Document]:
    docs = load_chunks()
    if domain:
        docs = [d for d in docs if d.metadata.get("domain") == domain]
    return docs


def load_judicial_interpretation() -> list[Document]:
    return load_collection("judicial_interpretation")


def load_labor_law() -> list[Document]:
    return load_collection("labor_law")


def load_labor_contract_law() -> list[Document]:
    return load_collection("labor_contract_law")


def load_labor_contract_regulation() -> list[Document]:
    return load_collection("labor_contract_regulation")


def load_labor_contract_bridge() -> dict:
    return load_bridge("labor_contract_law")
