"""
Map reviewer node — 逐条款并行审查，输出简洁 JSON。

两种模式:
  - blocking:  无 _stream_queues → 所有条款并行 asyncio.gather，返回 clause_reviews
  - streaming: _stream_queues 中有队列 → 每完成一条推送 _map_progress 事件

每条审查输出：
  {
    "compliant": true/false,
    "risks": [{"level": "高/中/低", "description": "...", "law_ref": "第X条"}],
    "suggestion": "修改建议"
  }
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from openai import BadRequestError, AuthenticationError
from langgraph.types import Command
from langgraph.constants import END
from langchain_core.runnables import RunnableConfig

from config.models import get_async_client, model_name
from graph.state import WorkflowState

logger = logging.getLogger(__name__)


MAP_REVIEWER_SYSTEM = """你是一位合同审查律师。只输出 JSON，不编造条文。"""

MAP_REVIEWER_PROMPT = """审查以下合同条款，指出风险点。

条款: {clause_title}
{clause_content}

法律依据（多级检索后的相关条文）:
{legal_basis}

只输出以下 JSON 格式，不要其他内容:
{{
  "compliant": true,
  "risks": [
    {{"level": "高", "description": "具体风险描述", "law_ref": "法律名称+条文号"}}
  ],
  "suggestion": "修改建议，无风险写'无需修改'"
}}

注意:
- 如果条款内容与法律依据对比后无明显违规，compliant=true, risks=[]
- risks 中的 law_ref 必须来自上面法律依据中的条文，不得编造
- 每条风险 description 控制在 30 字以内
- suggestion 控制在 50 字以内"""


def _parse_map_result(raw: str, clause_num: int, title: str) -> dict:
    """从 LLM 返回的文本中提取 JSON，兜底返回错误标记。"""
    try:
        # 尝试直接解析
        result = json.loads(raw)
    except json.JSONDecodeError:
        # 尝试提取 {...}
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
            except json.JSONDecodeError:
                result = {"compliant": True, "risks": [], "suggestion": "解析失败"}
        else:
            result = {"compliant": True, "risks": [], "suggestion": "解析失败"}

    result["clause_num"] = clause_num
    result["title"] = title
    result.setdefault("compliant", True)
    result.setdefault("risks", [])
    result.setdefault("suggestion", "无需修改")
    return result


async def map_reviewer_node(state: WorkflowState, config: RunnableConfig) -> dict:
    """逐条款并行审查。

    条款列表为空时透传（文本输入模式）。
    可恢复异常（Timeout/RateLimit/ConnectionError）向上抛让 RetryPolicy 重试。
    """
    clauses = state.get("clauses", [])
    if not clauses:
        return {}

    client = get_async_client()
    model = model_name("review_llm")
    legal_basis = state["retrieval_result"].get("assembled_text", "")
    # 每条条款的法律依据截断到 2000 字符（足够覆盖 3-4 条条文）
    legal_basis_short = legal_basis[:2000]
    thread_id = config.get("configurable", {}).get("thread_id", "")
    # 惰性导入避免循环依赖
    from graph.reduce_reviewer import _stream_queues as _queues
    token_queue: Optional[asyncio.Queue] = _queues.get(thread_id)
    total = len(clauses)

    async def _review_one(clause: dict, idx: int) -> dict:
        """审查单个条款，异常时返回错误标记。"""
        title = clause.get("title", f"条款{clause.get('clause_num', idx+1)}")
        content = clause.get("content", "")[:500]  # 每条款最多 500 字
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": MAP_REVIEWER_SYSTEM},
                    {"role": "user", "content": MAP_REVIEWER_PROMPT.format(
                        clause_title=title,
                        clause_content=content,
                        legal_basis=legal_basis_short,
                    )},
                ],
                temperature=0.3,
                max_tokens=400,
            )
            raw = resp.choices[0].message.content.strip()
            result = _parse_map_result(raw, clause.get("clause_num", idx + 1), title)
        except Exception as e:
            logger.warning("条款审查失败 (clause=%d): %s", clause.get("clause_num", idx + 1), e)
            result = {
                "clause_num": clause.get("clause_num", idx + 1),
                "title": title,
                "compliant": True,
                "risks": [],
                "suggestion": f"审查失败: {str(e)[:50]}",
            }

        # 流式模式：推送进度事件
        if token_queue is not None:
            try:
                await token_queue.put({
                    "_map_progress": {
                        "current": idx + 1,
                        "total": total,
                        "clause_title": title,
                    },
                })
            except Exception:
                pass

        return result

    try:
        # 所有条款并行审查
        tasks = [_review_one(clause, i) for i, clause in enumerate(clauses)]
        clause_reviews = await asyncio.gather(*tasks)
        return {"clause_reviews": list(clause_reviews)}
    except (BadRequestError, AuthenticationError) as e:
        if token_queue is not None:
            try:
                await token_queue.put({"_error": str(e)})
            except Exception:
                pass
        return Command(goto=END, update={"error": f"[条款审查] {e}"})
