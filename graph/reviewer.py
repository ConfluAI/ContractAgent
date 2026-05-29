"""
Reviewer node — LLM-powered contract review against retrieved legal basis.

Takes the contract text/questions and assembled legal knowledge, produces a
structured review with risk identification, amendment suggestions, and legal citations.
"""

from config.models import get_client, model_name
from graph.state import WorkflowState


REVIEWER_PROMPT = """你是一位资深合同法律师。请根据以下法律依据，对合同/法律问题进行审查分析。

审查问题 / 合同内容：
{input}

法律依据（多级检索+AI重排序后的最佳条文）：
{legal_basis}

法律适用原则：
- 民法典是所有合同关系的母法与通用基础，任何合同类型都适用
- 如提供了劳动法等专项法律条文，则专项法在对应领域优先适用（特别法优于一般法）
- 专项法未规定的，仍参照民法典的通用规则

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


def reviewer_node(state: WorkflowState) -> dict:
    """基于检索结果进行合同审查。"""
    if state.get("error"):
        return {}

    try:
        client = get_client()
        model = model_name("review_llm")

        legal_basis = state["retrieval_result"].get("assembled_text", "")

        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": REVIEWER_SYSTEM},
                {
                    "role": "user",
                    "content": REVIEWER_PROMPT.format(
                        input=state["input"],
                        legal_basis=legal_basis,
                    ),
                },
            ],
            temperature=0.3,
        )

        review_text = resp.choices[0].message.content.strip()
        return {"review_output": review_text}
    except Exception as e:
        return {"error": f"[合同审查] {e}"}
