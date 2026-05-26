"""
JSONL + 桥接文件加载器 — 加载拆分好的法律条文为 Document 对象。
"""

from __future__ import annotations

import json
from pathlib import Path
from langchain_core.documents import Document


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"


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


def load_chunks(jsonl_path: str | None = None) -> list[Document]:
    if jsonl_path is None:
        jsonl_path = str(_DATA_DIR / "civil_code_contract_chunks.jsonl")
    return _load_jsonl(jsonl_path)


def load_chunks_by_domain(domain: str | None = None) -> list[Document]:
    docs = load_chunks()
    if domain:
        docs = [d for d in docs if d.metadata.get("domain") == domain]
    return docs


def load_judicial_interpretation(jsonl_path: str | None = None) -> list[Document]:
    if jsonl_path is None:
        jsonl_path = str(_DATA_DIR / "judicial_interpretation_contract_general.jsonl")
    return _load_jsonl(jsonl_path)


def load_labor_law(jsonl_path: str | None = None) -> list[Document]:
    if jsonl_path is None:
        jsonl_path = str(_DATA_DIR / "labor_law_contract_chunks.jsonl")
    return _load_jsonl(jsonl_path)


def load_labor_contract_law(jsonl_path: str | None = None) -> list[Document]:
    if jsonl_path is None:
        jsonl_path = str(_DATA_DIR / "labor_contract_law_chunks.jsonl")
    return _load_jsonl(jsonl_path)


def load_labor_contract_regulation(jsonl_path: str | None = None) -> list[Document]:
    if jsonl_path is None:
        jsonl_path = str(_DATA_DIR / "labor_contract_regulation_chunks.jsonl")
    return _load_jsonl(jsonl_path)


def load_bridge(bridge_path: str | None = None) -> dict:
    if bridge_path is None:
        bridge_path = str(_DATA_DIR / "contract_law_bridge.json")
    with open(bridge_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_labor_contract_bridge(bridge_path: str | None = None) -> dict:
    if bridge_path is None:
        bridge_path = str(_DATA_DIR / "labor_contract_law_bridge.json")
    with open(bridge_path, "r", encoding="utf-8") as f:
        return json.load(f)
