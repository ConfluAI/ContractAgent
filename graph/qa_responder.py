"""
QA responder node — 合同条款咨询服务。

面向用户直接提问，输出四段式法律咨询回答。
"""

from config.models import get_client, model_name
from graph.state import WorkflowState

QA_RESPONDER_PROMPT = """你是一位资深法律顾问。请根据以下法律依据，回答用户的咨询问题。

用户问题：
{input}

法律依据（多级检索后的最佳条文）：
{legal_basis}

法律适用原则：
- 民法典是所有合同关系的母法与通用基础，任何合同类型都适用
- 如提供了劳动法等专项法律条文，则专项法在对应领域优先适用（特别法优于一般法）
- 专项法未规定的，仍参照民法典的通用规则

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


def qa_responder_node(state: WorkflowState) -> dict:
    if state.get("error"):
        return {}

    try:
        client = get_client()
        model = model_name("review_llm")

        legal_basis = state["retrieval_result"].get("assembled_text", "")

        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": QA_SYSTEM},
                {
                    "role": "user",
                    "content": QA_RESPONDER_PROMPT.format(
                        input=state["input"],
                        legal_basis=legal_basis,
                    ),
                },
            ],
            temperature=0.3,
        )

        answer = resp.choices[0].message.content.strip()
        return {"review_output": answer}
    except Exception as e:
        return {"error": f"[法律咨询] {e}"}
