"""
Dispatcher node — contract type classifier with keyword pre-filter.

民法典是所有合同的基础法律依据，永远检索。
其他专项法分支（劳动法等）根据合同类型按需激活。
"""

import json
import re

from config.models import get_client, model_name
from graph.state import WorkflowState

# 关键词 → 直接判定，跳过 LLM 调用
_LABOR_KEYWORDS = [
    "劳动合同", "劳动关系", "工资", "劳动报酬", "加班",
    "社保", "社会保险", "工伤", "竞业限制", "保密协议",
    "解除劳动合同", "经济补偿", "补偿金", "赔偿金", "劳动仲裁",
    "试用期", "最低工资", "劳务派遣", "女职工", "产假",
    "职业病", "安全生产", "劳动保护", "工会", "集体合同",
]

_CIVIL_KEYWORDS = [
    "买卖合同", "租赁合同", "借款合同", "服务合同", "合伙协议",
    "投资协议", "股权转让", "房产买卖", "商品房", "房屋租赁",
    "建设工程", "承揽合同", "运输合同", "仓储合同", "委托合同",
    "保证合同", "抵押合同", "质押", "定金", "违约金",
]


def _classify_by_keyword(text: str) -> dict | None:
    """关键词命中则直接返回分类，否则返回 None 走 LLM。"""
    has_labor = any(kw in text for kw in _LABOR_KEYWORDS)
    has_civil = any(kw in text for kw in _CIVIL_KEYWORDS)

    if has_labor and not has_civil:
        return {"contract_type": "labor", "extra_branches": ["labor"]}
    if has_civil and not has_labor:
        return {"contract_type": "civil", "extra_branches": []}
    # 模糊情况（都命中或都没命中）→ 走 LLM
    return None


DISPATCHER_PROMPT = """分析以下内容涉及哪种合同领域，仅输出 JSON：
{{"contract_type": "labor" | "civil", "extra_branches": ["labor"] 或 []}}

- civil: 民事/商事合同（买卖、租赁、借款、服务、合伙、投资等），extra_branches=[ ]
- labor: 涉及劳动关系（工资、社保、工伤、竞业限制、解除劳动合同等），extra_branches=["labor"]

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
    优先走关键词匹配，仅模糊情况才调 LLM。
    """
    if state.get("error"):
        return {}

    text = state["input"]
    try:
        # 1. 关键词快速通道
        result = _classify_by_keyword(text)
        if result is not None:
            return {
                "contract_type": result["contract_type"],
                "branches": ["civil"] + result["extra_branches"],
            }

        # 2. LLM 分类（仅模糊情况）
        client = get_client()
        model = model_name("review_llm")

        # 只传前 300 字，足够分类
        snippet = text[:300]
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一位资深律师。只输出 JSON。"},
                {"role": "user", "content": DISPATCHER_PROMPT.format(input=snippet)},
            ],
            temperature=0,
            max_tokens=100,
        )

        raw = resp.choices[0].message.content.strip()
        result = _parse_dispatcher_response(raw)
        contract_type = result["contract_type"]
        extra = result.get("extra_branches", [])

        branches = ["civil"] + extra
        return {
            "contract_type": contract_type,
            "branches": branches,
        }
    except Exception as e:
        return {"error": f"[合同分类] {e}"}
