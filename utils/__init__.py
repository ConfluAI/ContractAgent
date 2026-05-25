"""
LangGraph Document 工具 — 加载拆分好的民法典 chunks 为 Document 对象。
后续 LangGraph 工作流直接从此模块导入即可。
"""

import json
from pathlib import Path
from langchain_core.documents import Document


def load_chunks(jsonl_path: str | None = None) -> list[Document]:
    """
    从 JSONL 加载民法典 chunks，转为 LangChain Document 列表。

    每个 Document:
      - page_content: 含层级前缀的条文全文
      - metadata: 结构化元数据 (source, article_num, book, chapter, keywords 等)
    """
    if jsonl_path is None:
        jsonl_path = str(
            Path(__file__).resolve().parent.parent
            / "data"
            / "civil_code_contract_chunks.jsonl"
        )

    docs = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            chunk = json.loads(line)
            doc = Document(
                page_content=chunk["page_content"],
                metadata=chunk["metadata"],
            )
            docs.append(doc)

    return docs


def load_chunks_by_domain(domain: str | None = None) -> list[Document]:
    """加载全部 chunks，可按 domain 筛选（如 '合同履行', '违约责任'）。"""
    docs = load_chunks()
    if domain:
        docs = [d for d in docs if d.metadata.get("domain") == domain]
    return docs


def load_judicial_interpretation(jsonl_path: str | None = None) -> list[Document]:
    """加载合同编通则司法解释 chunks。"""
    if jsonl_path is None:
        jsonl_path = str(
            Path(__file__).resolve().parent.parent
            / "data"
            / "judicial_interpretation_contract_general.jsonl"
        )
    docs = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            chunk = json.loads(line)
            doc = Document(
                page_content=chunk["page_content"],
                metadata=chunk["metadata"],
            )
            docs.append(doc)
    return docs


def load_labor_law(jsonl_path: str | None = None) -> list[Document]:
    """加载劳动法合同相关 chunks。"""
    if jsonl_path is None:
        jsonl_path = str(
            Path(__file__).resolve().parent.parent
            / "data"
            / "labor_law_contract_chunks.jsonl"
        )
    return _load_jsonl(jsonl_path)


def load_labor_contract_law(jsonl_path: str | None = None) -> list[Document]:
    """加载劳动合同法 chunks。"""
    if jsonl_path is None:
        jsonl_path = str(
            Path(__file__).resolve().parent.parent
            / "data"
            / "labor_contract_law_chunks.jsonl"
        )
    return _load_jsonl(jsonl_path)


def load_labor_contract_regulation(jsonl_path: str | None = None) -> list[Document]:
    """加载劳动合同法实施条例 chunks。"""
    if jsonl_path is None:
        jsonl_path = str(
            Path(__file__).resolve().parent.parent
            / "data"
            / "labor_contract_regulation_chunks.jsonl"
        )
    return _load_jsonl(jsonl_path)


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


def load_bridge(bridge_path: str | None = None) -> dict:
    """加载双向桥接文件。

    返回:
      {
        "civil_to_interpretation": {str: list[dict]},  # 民法典条号 → 司法解释条目
        "interpretation_to_civil": {str: list[int]},   # 司法解释条号 → 民法典条号
      }
    """
    if bridge_path is None:
        bridge_path = str(
            Path(__file__).resolve().parent.parent
            / "data"
            / "contract_law_bridge.json"
        )
    with open(bridge_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_labor_contract_bridge(bridge_path: str | None = None) -> dict:
    """加载劳动合同法 ↔ 实施条例 双向桥接文件。

    返回:
      {
        "labor_contract_law_to_regulation": {str: list[dict]},
        "regulation_to_labor_contract_law": {str: list[int]},
      }
    """
    if bridge_path is None:
        bridge_path = str(
            Path(__file__).resolve().parent.parent
            / "data"
            / "labor_contract_law_bridge.json"
        )
    with open(bridge_path, "r", encoding="utf-8") as f:
        return json.load(f)
