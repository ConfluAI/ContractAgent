"""
五库入库 — 民法典 + 司法解释 + 劳动法 + 劳动合同法 + 实施条例。
同一持久化目录，五个独立 Chroma Collection。

首次运行建全部库，后续增量运行只建缺失的库。
"""

from pathlib import Path

from langchain_chroma import Chroma

from utils import (
    load_chunks,
    load_judicial_interpretation,
    load_labor_law,
    load_labor_contract_law,
    load_labor_contract_regulation,
)
from utils.retrieval import SiliconFlowEmbeddings

PERSIST_DIR = Path(__file__).resolve().parent / "data" / "chroma_civil_code"


def main(clear: bool = False) -> None:
    if clear and PERSIST_DIR.exists():
        import shutil
        shutil.rmtree(PERSIST_DIR)

    embeddings = SiliconFlowEmbeddings()

    collections = [
        ("civil_code", load_chunks, "民法典"),
        ("judicial_interpretation", load_judicial_interpretation, "司法解释"),
        ("labor_law", load_labor_law, "劳动法"),
        ("labor_contract_law", load_labor_contract_law, "劳动合同法"),
        ("labor_contract_regulation", load_labor_contract_regulation, "实施条例"),
    ]

    for col_name, loader, label in collections:
        docs = loader()
        print(f"Loading {label}: {len(docs)} documents")

        store = Chroma.from_documents(
            documents=docs,
            embedding=embeddings,
            collection_name=col_name,
            persist_directory=str(PERSIST_DIR),
        )
        print(f"  {col_name}: {store._collection.count()} vectors")

    print(f"\nDone. Persist directory: {PERSIST_DIR}")


if __name__ == "__main__":
    main()
