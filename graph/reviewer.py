"""
Reviewer node — LLM-powered contract review against retrieved legal basis.

单一节点，两种模式:
  - invoke():   writer=None → 阻塞等待完整响应 → return {"review_output": text}
  - astream():  writer 注入 → 逐 token 推送 → return {"review_output": full_text}
"""

from typing import Optional

from openai import BadRequestError, AuthenticationError
from langgraph.config import get_stream_writer, get_config
from langgraph.types import Command
from langgraph.constants import END

from config.models import get_async_client, model_name
from graph.state import WorkflowState


REVIEWER_PROMPT = """你是一位资深合同法律师。请根据以下法律依据，对合同/法律问题进行审查分析。

审查问题 / 合同内容：
{input}

法律依据（多级检索+AI重排序后的最佳条文）：
{legal_basis}

法律适用原则：
- 民法典是所有合同关系的母法与通用基础，任何合同类型都适用
- 如提供了劳动法等专项法律条文，则专项法在对应领域优先适用（特别法优于一般法）
- 专项法未规定的事项，参照民法典的通用规则（兜底补充）
- 专项法中涉及的法律术语、法律关系、法理概念，若需要深入理解其含义，
  应参考民法典中的相关基础规定（民法典提供了法律概念体系的底层框架）

请按以下结构输出审查报告：

一、审查主体
- 合同性质 / 所属法律领域
- 适用的主要法律规范（民法典为基础，如有专项法则标注优先适用）

二、法律分析
- 逐条分析问题涉及的法律要件
- 结合检索到的条文，判断合法性/合规性
- 引用具体条文编号及内容作为依据

三、风险识别
- 列出潜在的法律风险（如有）
- 标注风险等级（高/中/低）

四、修改建议
- 具体的合同条款修改建议（如适用）
- 法律行动建议（如适用）

五、法律依据索引
- 列出报告中引用的所有条文号
- 注明出处（法律名称 + 条文编号）

要求：
- 使用中国法律术语和行文规范
- 对条文引用务必准确，不得编造
- 如法律依据不足以做出判断，明确说明并建议补充检索方向"""

REVIEWER_SYSTEM = """你是一位资深合同法律师，擅长中国合同法与劳动法审查。
民法典是所有合同的基础法律依据，专项法（劳动法等）在对应领域优先适用。
你的审查意见基于提供的法律条文，不编造不存在的条文。"""

MAX_HISTORY_TURNS = 10


def _build_review_messages(
    input_text: str,
    legal_basis: str,
    conversation_history: Optional[list[dict]] = None,
) -> list[dict]:
    """构建审查 LLM 的消息列表。可注入对话历史用于多轮追问。"""
    messages = [{"role": "system", "content": REVIEWER_SYSTEM}]

    if conversation_history:
        truncated = conversation_history[-MAX_HISTORY_TURNS * 2:]
        messages.extend(truncated)

    messages.append({
        "role": "user",
        "content": REVIEWER_PROMPT.format(
            input=input_text,
            legal_basis=legal_basis,
        ),
    })
    return messages


# ── 统一节点（invoke / astream 共用）────────────────────────────────

async def reviewer_node(state: WorkflowState) -> dict:
    """合同审查节点。

    通过 get_stream_writer() 判断模式：
      - RuntimeError → 阻塞模式（ainvoke），等完整响应
      - 拿到 writer → 流式模式（astream custom），逐 token 推送

    错误处理：
      - BadRequestError / AuthenticationError → 致命，设 error
      - Timeout / RateLimit / 连接中断 → 向上抛，checkpoint 恢复
    """
    client = get_async_client()
    model = model_name("review_llm")
    legal_basis = state["retrieval_result"].get("assembled_text", "")
    cfg = get_config()
    conversation_history = cfg.get("configurable", {}).get("conversation_history")

    # 判断运行模式
    try:
        writer = get_stream_writer()
    except RuntimeError:
        writer = None

    try:
        if writer is None:
            # ── 阻塞模式 ──
            resp = await client.chat.completions.create(
                model=model,
                messages=_build_review_messages(state["input"], legal_basis, conversation_history),
                temperature=0.3,
            )
            review_text = resp.choices[0].message.content.strip()
            return {"review_output": review_text, "retrieval_result": {}}
        else:
            # ── 流式模式 ──
            stream = await client.chat.completions.create(
                model=model,
                messages=_build_review_messages(state["input"], legal_basis, conversation_history),
                temperature=0.3,
                stream=True,
            )
            full_text = ""
            async for chunk in stream:
                token = chunk.choices[0].delta.content or ""
                if token:
                    full_text += token
                    writer({"token": token})
            return {"review_output": full_text, "retrieval_result": {}}
    except (BadRequestError, AuthenticationError) as e:
        return Command(goto=END, update={"error": f"[合同审查] {e}"})
    # Timeout / RateLimit / ConnectionError / InternalServerError
    # 不捕获 → 向上抛给 LangGraph，checkpoint 保存后可重试
