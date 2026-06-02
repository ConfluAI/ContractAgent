"""
QA responder node — 合同条款咨询服务。

单一节点，两种模式:
  - invoke():   writer=None → 阻塞等待完整响应 → return {"review_output": text}
  - astream():  writer 注入 → 逐 token 推送 → return {"review_output": full_text}
"""

from typing import Optional

from openai import BadRequestError, AuthenticationError
from langgraph.config import get_stream_writer, get_config

from config.models import get_async_client, model_name
from graph.state import WorkflowState

QA_RESPONDER_PROMPT = """你是一位资深法律顾问。请根据以下法律依据，回答用户的咨询问题。

用户问题：
{input}

法律依据（多级检索后的最佳条文）：
{legal_basis}

法律适用原则：
- 民法典是所有合同关系的母法与通用基础，任何合同类型都适用
- 如提供了劳动法等专项法律条文，则专项法在对应领域优先适用（特别法优于一般法）
- 专项法未规定的事项，参照民法典的通用规则（兜底补充）
- 专项法中涉及的法律术语、法律关系、法理概念，若需要深入理解其含义，
  应参考民法典中的相关基础规定（民法典提供了法律概念体系的底层框架）

请按以下结构回答：

一、直接结论
- 用 1-2 句话给出核心结论

二、法律依据
- 列出适用的法律条文及具体内容
- 说明条文如何适用于本问题
- 如有多个条文，说明它们之间的关系

三、法律分析
- 将法律要件逐条对应到用户问题中的事实
- 分析合法/不合法的理由

四、操作建议
- 用户接下来可以采取的法律行动
- 需要注意的时效、证据等事项

要求：
- 使用中国法律术语，表达准确、通俗易懂
- 对条文引用务必准确，不得编造
- 如法律依据不足以做出判断，明确说明"""

QA_SYSTEM = """你是一位资深中国法律顾问，擅长合同法与劳动法。
民法典是所有合同的基础法律依据，专项法（劳动法等）在对应领域优先适用。
你基于提供的法律条文回答，不编造不存在的条文。
回答既要专业准确，也要让普通用户能听懂。"""

MAX_HISTORY_TURNS = 10


def _build_qa_messages(
    input_text: str,
    legal_basis: str,
    conversation_history: Optional[list[dict]] = None,
) -> list[dict]:
    """构建 QA 的消息列表。可注入对话历史用于多轮追问。"""
    messages = [{"role": "system", "content": QA_SYSTEM}]

    if conversation_history:
        truncated = conversation_history[-MAX_HISTORY_TURNS * 2:]
        messages.extend(truncated)

    messages.append({
        "role": "user",
        "content": QA_RESPONDER_PROMPT.format(
            input=input_text,
            legal_basis=legal_basis,
        ),
    })
    return messages


# ── 统一节点（invoke / astream 共用）────────────────────────────────

async def qa_responder_node(state: WorkflowState) -> dict:
    """法律咨询节点。

    通过 get_stream_writer() 判断模式：
      - RuntimeError → 阻塞模式（ainvoke）
      - 拿到 writer → 流式模式（astream custom），逐 token 推送
    """
    client = get_async_client()
    model = model_name("review_llm")
    legal_basis = state["retrieval_result"].get("assembled_text", "")
    cfg = get_config()
    conversation_history = cfg.get("configurable", {}).get("conversation_history")

    try:
        writer = get_stream_writer()
    except RuntimeError:
        writer = None

    try:
        if writer is None:
            resp = await client.chat.completions.create(
                model=model,
                messages=_build_qa_messages(state["input"], legal_basis, conversation_history),
                temperature=0.3,
            )
            answer = resp.choices[0].message.content.strip()
            return {"review_output": answer, "retrieval_result": {}}
        else:
            stream = await client.chat.completions.create(
                model=model,
                messages=_build_qa_messages(state["input"], legal_basis, conversation_history),
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
        return {"error": f"[法律咨询] {e}"}
    # Timeout / RateLimit / ConnectionError / InternalServerError
    # 不捕获 → 向上抛给 LangGraph，checkpoint 保存后可重试
