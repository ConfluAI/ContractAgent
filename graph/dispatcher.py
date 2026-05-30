"""
Dispatcher node — 判断是否激活专项法分支。

民法典是所有合同的基础法律依据，永远检索，无需判断。
只判断是否需要激活劳动法等专项分支。
未来新增分支（租赁、消费者保护等）只需加关键词列表 + 判断逻辑。
"""

import json
import re

from config.models import get_client, model_name
from graph.state import WorkflowState

# ── 各分支关键词（只加需要判定的专项分支）────────────────────────────

_LABOR_KEYWORDS = [
    "劳动合同", "劳动关系", "工资", "劳动报酬", "加班",
    "社保", "社会保险", "工伤", "竞业限制", "保密协议",
    "解除劳动合同", "经济补偿", "补偿金", "赔偿金", "劳动仲裁",
    "试用期", "最低工资", "劳务派遣", "女职工", "产假",
    "职业病", "安全生产", "劳动保护", "工会", "集体合同",
]


def _extra_branches_by_keyword(text: str) -> list[str]:
    """关键词命中 → 直接激活对应分支，跳过 LLM。未命中返回空列表。"""
    extra: list[str] = []
    if any(kw in text for kw in _LABOR_KEYWORDS):
        extra.append("labor")
    # 未来扩展：if any(kw in text for kw in _LEASE_KEYWORDS): extra.append("lease")
    return extra


def _extra_branches_by_llm(text: str) -> list[str]:
    """LLM 判断是否需要激活专项分支（关键词未命中的模糊情况）。"""
    client = get_client()
    model = model_name("review_llm")

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是一位资深律师。只输出 JSON。"},
            {"role": "user", "content": DISPATCHER_PROMPT.format(input=text[:300])},
        ],
        temperature=0,
        max_tokens=100,
    )

    raw = resp.choices[0].message.content.strip()
    result = _parse_dispatcher_response(raw)
    return result.get("extra_branches", [])


DISPATCHER_PROMPT = """判断以下内容是否涉及劳动法领域，仅输出 JSON：
{{"contract_type": "labor" | "civil", "extra_branches": ["labor"] 或 []}}

- labor: 涉及劳动合同、劳动关系、工资、社保、工伤、竞业限制、解除劳动合同等 → extra_branches=["labor"]
- civil: 不涉及劳动法的民事/商事合同（买卖、租赁、借款、服务等）→ extra_branches=[]

用户输入：
{input}

只输出 JSON。"""


def _parse_dispatcher_response(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Dispatcher 未返回有效 JSON: {raw[:200]}")
    return json.loads(match.group())


def dispatcher_node(state: WorkflowState) -> dict:
    """决定激活哪些专项分支。civil 永远激活，无需判断。"""
    if state.get("error"):
        return {}

    text = state["input"]
    try:
        # 1. 关键词快速通道（命中直接激活，不走 LLM）
        extra = _extra_branches_by_keyword(text)
        if extra:
            return {
                "contract_type": extra[0],
                "branches": ["civil"] + extra,
            }

        # 2. LLM 判断（关键词未命中但可能仍是劳动法场景）
        extra = _extra_branches_by_llm(text)
        contract_type = extra[0] if extra else "civil"
        return {
            "contract_type": contract_type,
            "branches": ["civil"] + extra,
        }
    except Exception as e:
        return {"error": f"[合同分类] {e}"}
