"""
Dispatcher node — 判断是否激活专项法分支 + 领域拒识。

民法典是所有合同的基础法律依据，永远检索，无需判断。
只判断是否需要激活劳动法等专项分支。

领域拒识:
  - 非合同法律问题 → Command(goto=END)，提示用户本系统仅支持合同审查
  - 关键词命中劳动法 → 直接激活 labor（不走 LLM，省 token）
  - 关键词未命中 → LLM 三分类（labor / civil / reject）

未来新增分支（租赁、消费者保护等）只需加关键词列表 + 判断逻辑。
"""

import json
import re

from openai import BadRequestError, AuthenticationError
from langgraph.types import Command
from langgraph.constants import END

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
    return extra


def _dispatcher_by_llm(text: str) -> dict:
    """LLM 三分类：labor / civil / reject。

    Returns:
      {"contract_type": "labor"|"civil"|"reject", "extra_branches": [...]}

    reject → 非合同法律问题，应由上游做友好提示。
    """
    client = get_client()
    model = model_name("review_llm")

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是一位资深律师。只输出 JSON，不输出其他内容。"},
            {"role": "user", "content": DISPATCHER_PROMPT.format(input=text[:300])},
        ],
        temperature=0,
        max_tokens=100,
    )

    raw = resp.choices[0].message.content.strip()
    return _parse_dispatcher_response(raw)


DISPATCHER_PROMPT = """判断以下内容属于哪种类型，仅输出 JSON：

{{"contract_type": "labor" | "civil" | "reject", "extra_branches": ["labor"] 或 []}}

分类标准:
- labor: 涉及劳动合同、劳动关系、工资、社保、工伤、竞业限制、解除劳动合同等劳动法问题
  → extra_branches=["labor"]
- civil: 涉及民事/商事合同（买卖、租赁、借款、服务、承包等）的审查
  → extra_branches=[]
- reject: 以下情况拒绝审查:
    · 不属于合同/法律问题（如日常闲聊、技术问题、烹饪教程等）
    · 属于法律问题但不涉及合同（如刑事犯罪、交通事故、离婚财产、继承、行政等）
    · 无法判断意图的模糊输入
  → extra_branches=[]

用户输入：
{input}

只输出 JSON。"""

REJECT_MESSAGE = (
    "抱歉，本系统当前仅支持**合同审查**相关的法律服务。\n\n"
    "您可以尝试：\n"
    "- 上传一份合同文件（.docx / .pdf）进行审查\n"
    "- 输入合同条款咨询法律问题\n"
    "- 询问合同法、劳动法相关问题\n\n"
    "如需其他法律服务（刑事、婚姻、交通、行政等），请使用通用法律咨询。"
)


def _parse_dispatcher_response(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Dispatcher 未返回有效 JSON: {raw[:200]}")
    return json.loads(match.group())


def dispatcher_node(state: WorkflowState) -> dict:
    """决定激活哪些专项分支 + 领域拒识。

    - 关键词命中 → 直接激活（零 LLM 成本）
    - 关键词未命中 → LLM 三分类
    - reject → Command(goto=END)，友好提示

    错误处理:
      - BadRequestError / AuthenticationError → 致命，Command(goto=END)
      - Timeout / RateLimit / 连接中断 / JSON 解析失败 → 向上抛，
        RetryPolicy 或调用方重试循环接管
    """
    judge_text = state.get("contract_name") or state["input"]

    # 空输入防御
    if not judge_text.strip():
        return Command(goto=END, update={"error": "请输入合同内容或法律问题"})

    try:
        # 1. 关键词快速通道（命中直接激活，不走 LLM）
        extra = _extra_branches_by_keyword(judge_text)
        if extra:
            return {
                "contract_type": extra[0],
                "branches": ["civil"] + extra,
            }

        # 2. LLM 三分类
        result = _dispatcher_by_llm(judge_text[:300])
        contract_type = result.get("contract_type", "civil")

        # 3. 领域拒识
        if contract_type == "reject":
            return Command(goto=END, update={"error": REJECT_MESSAGE})

        extra = result.get("extra_branches", [])
        return {
            "contract_type": contract_type,
            "branches": ["civil"] + extra,
        }
    except (BadRequestError, AuthenticationError) as e:
        return Command(goto=END, update={"error": f"[合同分类] {e}"})
