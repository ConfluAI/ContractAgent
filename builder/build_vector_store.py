"""
向量库入库 — 根据 COLLECTION_SOURCES 注册表自动建库。

新增法律文档只需在 retrieval/loaders.py 的 COLLECTION_SOURCES 加一条记录，
无需修改此文件。

用法：
  python -m builder.build_vector_store          # 增量（追加到已有库）
  python -m builder.build_vector_store --clear  # 清空重建
"""

import argparse
from pathlib import Path

from langchain_chroma import Chroma

from retrieval.loaders import COLLECTION_SOURCES, load_collection
from retrieval.embeddings import SiliconFlowEmbeddings

PERSIST_DIR = Path(__file__).resolve().parent.parent / "data" / "chroma_civil_code"


def main(clear: bool = False) -> None:
    if clear and PERSIST_DIR.exists():
        import shutil
        shutil.rmtree(PERSIST_DIR)
        print("Cleared existing vector store.\n")

    embeddings = SiliconFlowEmbeddings()

    for col_name, spec in COLLECTION_SOURCES.items():
        docs = load_collection(col_name)
        label = spec["label"]
        print(f"Loading {label} ({col_name}): {len(docs)} documents")

        store = Chroma.from_documents(
            documents=docs,
            embedding=embeddings,
            collection_name=col_name,
            persist_directory=str(PERSIST_DIR),
        )
        print(f"  → {store._collection.count()} vectors")

    print(f"\nDone. Persist directory: {PERSIST_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="向量库入库")
    parser.add_argument("--clear", action="store_true", help="清空后重建全部")
    args = parser.parse_args()
    main(clear=args.clear)
