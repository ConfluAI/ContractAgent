"""
Reduce reviewer node — 汇总逐条款审查结果，输出完整五段式报告。

两种模式:
  - blocking:  无 _stream_queues → 阻塞等待完整响应
  - streaming: _stream_queues 中有队列 → 逐 token 推送
"""

from __future__ import annotations

import asyncio
from typing import Optional

from openai import BadRequestError, AuthenticationError
from langgraph.types import Command
from langgraph.constants import END
from langchain_core.runnables import RunnableConfig

from config.models import get_async_client, model_name
from graph.state import WorkflowState

# 模块级 token 队列注册表，key=thread_id
_stream_queues: dict[str, asyncio.Queue] = {}


REDUCE_REVIEWER_SYSTEM = """你是一位资深合同法律师，擅长中国合同法与劳动法审查。
民法典是所有合同的基础法律依据，专项法（劳动法等）在对应领域优先适用。
你基于条款审查结果撰写最终报告，不编造不存在的条文。"""

REDUCE_REVIEWER_PROMPT = """请根据以下条款审查结果和法律依据，生成完整的合同审查报告。

合同名称: {contract_name}

法律依据（多级检索+AI重排序后的最佳条文）:
{legal_basis}

各条款审查结果:
{clause_summaries}

法律适用原则:
- 民法典是所有合同关系的母法与通用基础，任何合同类型都适用
- 如提供了劳动法等专项法律条文，则专项法在对应领域优先适用（特别法优于一般法）
- 专项法未规定的事项，参照民法典的通用规则（兜底补充）

请按以下结构输出审查报告:

一、审查主体
- 合同性质 / 所属法律领域
- 适用的主要法律规范（民法典为基础，如有专项法则标注优先适用）

二、法律分析
- 逐条分析问题涉及的法律要件
- 结合检索到的条文，判断合法性/合规性
- 引用具体条文编号及内容作为依据
- 标记合规的条款，重点展开有风险的条款

三、风险识别
- 汇总所有条款审查中发现的风险
- 标注风险等级（高/中/低）
- 按风险等级排序：高风险优先

四、修改建议
- 针对每个风险点的具体合同条款修改建议
- 法律行动建议（如适用）

五、法律依据索引
- 列出报告中引用的所有条文号
- 注明出处（法律名称 + 条文编号）

要求:
- 使用中国法律术语和行文规范
- 对条文引用务必准确，不得编造
- 如某条款审查结果标记为 compliant=true，简要说明即可
- 如法律依据不足以做出判断，明确说明并建议补充检索方向"""

MAX_HISTORY_TURNS = 10


def _build_reduce_messages(
    contract_name: str,
    legal_basis: str,
    clause_summaries: str,
    conversation_history: Optional[list[dict]] = None,
) -> list[dict]:
    """构建汇总 LLM 的消息列表。"""
    messages = [{"role": "system", "content": REDUCE_REVIEWER_SYSTEM}]

    if conversation_history:
        truncated = conversation_history[-MAX_HISTORY_TURNS * 2:]
        messages.extend(truncated)

    messages.append({
        "role": "user",
        "content": REDUCE_REVIEWER_PROMPT.format(
            contract_name=contract_name,
            legal_basis=legal_basis,
            clause_summaries=clause_summaries,
        ),
    })
    return messages


def _format_clause_reviews(clause_reviews: list[dict]) -> str:
    """将结构化审查结果格式化为 LLM 可读文本。"""
    lines = []
    for r in clause_reviews:
        num = r.get("clause_num", "?")
        title = r.get("title", "")
        compliant = "合规" if r.get("compliant", True) else "有风险"
        risks = r.get("risks", [])
        suggestion = r.get("suggestion", "无需修改")

        lines.append(f"第{num}条 {title} [{compliant}]")
        if risks:
            for risk in risks:
                level = risk.get("level", "低")
                desc = risk.get("description", "")
                law = risk.get("law_ref", "")
                lines.append(f"  - 风险({level}): {desc} | 依据: {law}")
        lines.append(f"  - 建议: {suggestion}")
        lines.append("")
    return "\n".join(lines)


async def reduce_reviewer_node(state: WorkflowState, config: RunnableConfig) -> dict:
    """汇总条款审查 → 完整五段式报告。

    clauses 为空时透传（文本输入模式，走旧 reviewer）。
    """
    clauses = state.get("clauses", [])
    if not clauses:
        return {}

    client = get_async_client()
    model = model_name("review_llm")
    contract_name = state.get("contract_name", "未知合同")
    legal_basis = state["retrieval_result"].get("assembled_text", "")
    clause_reviews = state.get("clause_reviews", [])
    conversation_history = config.get("configurable", {}).get("conversation_history")
    thread_id = config.get("configurable", {}).get("thread_id", "")
    token_queue: Optional[asyncio.Queue] = _stream_queues.get(thread_id)

    # 格式化条款审查摘要
    clause_summaries = _format_clause_reviews(clause_reviews)

    try:
        if token_queue is None:
            # ── 阻塞模式 ──
            resp = await client.chat.completions.create(
                model=model,
                messages=_build_reduce_messages(
                    contract_name, legal_basis, clause_summaries, conversation_history,
                ),
                temperature=0.3,
            )
            review_text = resp.choices[0].message.content.strip()
            return {"review_output": review_text, "retrieval_result": state.get("retrieval_result", {})}
        else:
            # ── 流式模式 ──
            stream = await client.chat.completions.create(
                model=model,
                messages=_build_reduce_messages(
                    contract_name, legal_basis, clause_summaries, conversation_history,
                ),
                temperature=0.3,
                stream=True,
            )
            full_text = ""
            async for chunk in stream:
                token = chunk.choices[0].delta.content or ""
                if token:
                    full_text += token
                    await token_queue.put({"token": token})
            return {"review_output": full_text, "retrieval_result": state.get("retrieval_result", {})}
    except (BadRequestError, AuthenticationError) as e:
        if token_queue is not None:
            await token_queue.put({"_error": str(e)})
        return Command(goto=END, update={"error": f"[报告汇总] {e}"})
