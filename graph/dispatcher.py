"""
Dispatcher node — LLM-powered contract type classifier.

Analyzes user input to determine whether the contract is labor, civil, or mixed,
then maps to the appropriate retrieval branches.
"""

import json
import re

from config.models import get_client, model_name
from graph.state import WorkflowState


DISPATCHER_PROMPT = """你是一位资深律师，擅长快速识别合同类型。

请分析以下内容属于哪种合同类型，并仅输出 JSON：

{{
  "contract_type": "labor" | "civil" | "mixed",
  "reason": "简短的判断理由（1-2句）"
}}

分类标准：
- labor: 涉及劳动关系、劳动合同、工资、社保、工伤、竞业限制、解除劳动合同等
- civil: 涉及买卖、租赁、借款、服务、合伙、投资等民事/商事合同
- mixed: 同时涉及劳动关系和民事合同关系，或难以明确区分的混合情形

注意：如果用户只是在询问法律问题（如"拖欠工资能否解除合同"），请根据问题涉及的领域判断。
例如涉及工资、解除劳动合同 → labor；涉及货款、违约金 → civil。

用户输入：
{input}

只输出 JSON，不要输出其他内容。"""


def _parse_dispatcher_response(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Dispatcher 未返回有效 JSON: {raw[:200]}")
    return json.loads(match.group())


def dispatcher_node(state: WorkflowState) -> dict:
    """分析合同类型，决定激活哪些检索分支。"""
    client = get_client()
    model = model_name("review_llm")

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是一位资深律师。只输出 JSON，不要输出其他内容。"},
            {"role": "user", "content": DISPATCHER_PROMPT.format(input=state["input"])},
        ],
        temperature=0,
    )

    raw = resp.choices[0].message.content.strip()
    result = _parse_dispatcher_response(raw)
    contract_type = result["contract_type"]

    # Map contract_type to branches
    branch_map = {
        "labor": ["labor", "civil"],
        "civil": ["civil"],
        "mixed": ["labor", "civil"],
    }
    branches = branch_map.get(contract_type, ["civil"])

    return {
        "contract_type": contract_type,
        "branches": branches,
    }
