"""
Dispatcher node — LLM-powered contract type classifier.

民法典是所有合同的基础法律依据，永远检索。
其他专项法分支（劳动法等）根据合同类型按需激活。
"""

import json
import re

from config.models import get_client, model_name
from graph.state import WorkflowState


DISPATCHER_PROMPT = """你是一位资深律师。请分析以下内容涉及哪种合同领域，仅输出 JSON：

{{
  "contract_type": "labor" | "civil",
  "extra_branches": ["labor"] 或 []
}}

分类标准：
- civil: 纯粹民事/商事合同，只涉及买卖、租赁、借款、服务、合伙、投资等
  → 此时 extra_branches 为空 []
- labor: 涉及劳动合同、劳动关系、工资、社保、工伤、竞业限制、解除劳动合同等
  → 此时 extra_branches 含 "labor"

重要概念：
- 民法典是所有合同关系的母法与基础，无论什么合同类型都必须参考
- 劳动法是专门调整劳动合同的特别法，仅在涉及劳动关系时才激活
- 即使内容同时提到雇佣关系和民事关系，也请按核心争议判断主要类型

用户输入：
{input}

只输出 JSON。"""


def _parse_dispatcher_response(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Dispatcher 未返回有效 JSON: {raw[:200]}")
    return json.loads(match.group())


def dispatcher_node(state: WorkflowState) -> dict:
    """分析合同类型，决定激活哪些检索分支。

    民法典分支永远激活（civil 是所有合同的母法）。
    其他专项分支（labor 等）根据 LLM 判断按需激活。
    """
    client = get_client()
    model = model_name("review_llm")

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是一位资深律师。只输出 JSON。"},
            {"role": "user", "content": DISPATCHER_PROMPT.format(input=state["input"])},
        ],
        temperature=0,
    )

    raw = resp.choices[0].message.content.strip()
    result = _parse_dispatcher_response(raw)
    contract_type = result["contract_type"]
    extra = result.get("extra_branches", [])

    # civil 永远在列表中（民法典是所有合同的母法）
    branches = ["civil"] + extra

    return {
        "contract_type": contract_type,
        "branches": branches,
    }
