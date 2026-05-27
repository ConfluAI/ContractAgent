import asyncio

from graph.workflow import run_contract_review


async def run_review(user_input: str = "", file_path: str = "") -> dict:
    result = await asyncio.to_thread(run_contract_review, user_input=user_input, file_path=file_path)
    return {
        "contract_type": result.get("contract_type", ""),
        "branches": result.get("branches", []),
        "review_output": result.get("review_output", ""),
        "error": result.get("error", ""),
    }
