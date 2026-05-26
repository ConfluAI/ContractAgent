"""
LangGraph workflow state — defines the shape of data flowing through the graph.
"""

from __future__ import annotations

from typing import TypedDict


class WorkflowState(TypedDict):
    input: str              # contract text or review question (always populated)
    file_path: str          # optional path to docx/pdf file, parsed into input
    contract_type: str      # "labor" | "civil" | "mixed" — set by dispatcher
    branches: list[str]     # derived from contract_type, fed to retriever
    retrieval_result: dict  # output of ContractRetriever.search()
    review_output: str      # final LLM contract review
    error: str              # error message if any node fails
