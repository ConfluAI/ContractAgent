# ContractAgent — 合同审查智能体

基于 LangGraph 多智能体框架 + RAG 的中国合同法律审查系统。本文档描述系统的技术架构、工作流编排和核心机制。

## 整体架构

```
用户输入（文本 / docx / pdf）
        │
        ▼
┌─────────────────────────────────────────────────┐
│                  LangGraph 工作流                 │
│                                                 │
│  Parser ──▶ Dispatcher ──▶ Retriever × N        │
│    │            │               │               │
│    │       [领域拒识]      [并行向量检索]          │
│    │       [关键词快通道]    [桥接补全]            │
│    │       [LLM 三分类]     [BGE Rerank]         │
│    │                         │                  │
│    │                    Merge Retrieval          │
│    │                         │                  │
│    │                    ┌────┴────┐              │
│    │                    │ 条件路由  │              │
│    │                    └────┬────┘              │
│    │               clauses≠[] │ clauses=[]       │
│    │                    ▼              ▼         │
│    │            Map Reviewer    Reviewer         │
│    │            (逐条并行审查)   (单次审查)        │
│    │                    │                        │
│    │            Reduce Reviewer                  │
│    │            (汇总五段式报告)                   │
│    │                    │                        │
│    └────────────────────┼────────────────────────│
│                         ▼                        │
│                   END（返回报告）                  │
└─────────────────────────────────────────────────┘
```

---

## 一、输入处理：从原始文件到结构化条款

### 1.1 文件解析

用户可上传 `.docx` / `.pdf` 合同文件，或直接输入文本。文件解析在 `parser_node` 中完成，使用 `python-docx` 和 `pypdf` 提取全文。解析后的**全文不进入 WorkflowState**——这是核心设计决策：原始合同文本可能长达数万字，放入 state 会导致 checkpoint 体积膨胀、LLM 上下文溢出。

### 1.2 条款切分

`split_contract_clauses()` 将合同正文按条款拆分为结构化列表，三级降级策略：

| 优先级 | 策略 | 触发条件 |
|:--:|------|------|
| 1 | 正则 `第[一二三四五六七八九十百千\d]+条` 切分 | 文档中存在"第X条"结构（绝大多数中文合同） |
| 2 | 按句号/换行二次切分 | 单条内容超过 1500 字符 |
| 3 | 按双换行切分 → 固定窗口兜底 | 文档中完全找不到"第X条" |

每条条款以结构化的 `dict` 存储：`{clause_num, sub_num, title, content}`。对于被二次拆分的超长条款，通过 `sub_num` 标记子段落，下游审查时仍以完整语义单元处理。

### 1.3 检索 Query 构建

为避免将全部条款送入检索器（token 浪费），parser 从合同名 + 前 3 条条款摘要拼装检索 query（约 300 字符），存入 `state["input"]` 覆盖原始用户输入。

---

## 二、合同分类与领域拒识：Dispatcher

Dispatcher 是工作流的第一个决策节点，完成两件事：**确定激活哪些法律检索分支**、**拒绝非合同输入**。

### 2.1 关键词快速通道

在调用 LLM 之前，先用关键词做秒级匹配。以劳动法为例，维护了 25 个高区分度关键词（"劳动合同"、"竞业限制"、"工伤"、"试用期" 等）。命中则直接激活 `labor` 分支，**零 LLM 成本**。未来新增专项法分支（如消费者保护、房屋租赁）只需扩充关键词列表。

### 2.2 LLM 三分类

关键词未命中时，调用 LLM（DeepSeek-V3，`max_tokens=100`，`temperature=0`）做三分类：

```
labor  → 激活 civil + labor 双分支
civil  → 激活 civil 单分支
reject → Command(goto=END)，终止工作流
```

`reject` 覆盖三类场景：非法律问题（日常闲聊）、非合同法律问题（刑事/婚姻/行政）、模糊输入。拒识发生在检索之前，避免无效的向量搜索和 API 调用。

### 2.3 分类依据

Dispatcher 不直接对合同全文分类，而是使用 `state["contract_name"]`（parser 从文档首行提取的合同名称，如"劳动合同"、"房屋买卖合同"）——合同名称本身就携带了极强的类型信号，单凭 LLM 对名称的判断即可达到高准确率。

### 2.4 分支设计

所有合同类型中，民法典 (`civil`) 作为母法**始终激活**（不参与分类判断）。Dispatcher 只需决定是否激活额外的专项法分支（当前为 `labor`）。BRANCH_SPEC 配置如下：

```python
BRANCH_SPEC = {
    "civil": {"priority": 2, "label": "合同通用规范",
              "description": "民法典+合同编解释"},
    "labor": {"priority": 1, "label": "劳动法律规范",
              "description": "劳动合同法+实施条例+劳动法，特别法优先适用"},
}
```

`priority` 决定最终报告中的排列顺序（特别法优先于一般法），以及 `assembled_text` 的拼接次序。

---

## 三、法律检索管线：多分支并行 + 桥接 + Rerank

检索管线是系统的核心——如何从 856 条法律条文中找出与用户合同最相关的几条。

### 3.1 多路向量检索并行

每个分支内部，多条向量搜索**并行发出**（`ThreadPoolExecutor`，max_workers=6）。以 `civil` 分支为例：

```
civil 分支
  ├── Chroma("civil_code").similarity_search(query, k=2)      → 民法典条文
  └── Chroma("judicial_interpretation").similarity_search(query, k=2) → 司法解释
```

`labor` 分支同理，3 路并行（劳动合同法 + 实施条例 + 劳动法）。分支之间也并行执行（LangGraph fan-out 机制），多个 branch_retriever 节点同时跑。

### 3.2 桥接补全（1-hop Bridge）

向量检索天然不完整：用户问试用期问题，`civil_code` 集合召回了民法典相关条文，但 `labor_contract_law` 中有更精确的试用期条款可能因相似度不够高而漏掉。

桥接机制解决这个问题：系统预先构建了条文之间的**引用关系映射表**（JSON），记录了法典条文编号与下位法条文编号之间的对应关系。检索后做 1-hop 扩展：

```
civil_code 第X条 ←→ judicial_interpretation 对应条款
labor_contract_law 第X条 ←→ labor_contract_regulation 对应条款
```

扩展后的条文对（pair）从 Chroma 缓存中按 `article_num` 精确取出。这保证了法律体系的内在关联不会被向量检索的近似匹配遗漏。

### 3.3 BGE Rerank（Cross-Encoder）

桥接后候选集膨胀（通常 10-30 个条文对），全部送入 LLM 上下文过长且不经济。系统使用 **BGE-Reranker-v2-m3**（cross-encoder）对所有候选做精细相关性评分：

- 每个候选条文块与用户 query 独立打分（`relevance_score`）
- `threshold=0.5`：低于阈值的标记为 `IRRELEVANT`，不送下游
- 兜底保护：若全部被过滤，保留最高分的 1 条，避免空白
- 每分支最多保留 `max_rerank_blocks=5` 条

与 LLM Rerank 的对比：BGE Reranker 是专用 cross-encoder，延迟约 100ms，免费，且排序一致性优于通用 LLM 的 pointwise 打分。

### 3.4 不使用 Query Expansion / HyDE / Multi-Query 的原因

合同审查对条文来源的精确引用要求极高，Query Expansion 生成的多变体 query 可能引入语义漂移，导致召回的条文看似相关实则适用前提不同（如混淆"合同解除"与"合同无效"的法律要件）。系统选择用桥接补全 + BGE Rerank 替代膨胀-召回-过滤的套路，以保证精确性优先。

---

## 四、LangGraph 工作流编排

### 4.1 图结构

系统编译了两个独立的 StateGraph（共用同一个 WorkflowState schema）：

**Review Graph：**

```
START → parser → dispatcher
                     │
           ┌─────────┴──────────┐
           ▼                    ▼
    civil_retriever      labor_retriever
           │                    │
           └─────────┬──────────┘
                     ▼
              merge_retrieval
                     │
              ┌──────┴──────┐
              │  条件路由     │
              └──────┬──────┘
          clauses≠[] │ clauses=[]
              ▼              ▼
        map_reviewer    reviewer
              │              │
              ▼              │
        reduce_reviewer      │
              │              │
              ▼              ▼
             END ←───────────┘
```

**QA Graph（法律咨询）：** 跳过 parser 和 map/reduce，`dispatcher → retrievers → merge → qa_responder → END`。

### 4.2 两种图执行模式

每个需要 LLM 生成的节点（reviewer / map_reviewer / reduce_reviewer / qa_responder）同时支持两种模式：

| 模式 | 触发条件 | 行为 |
|------|------|------|
| **阻塞** | `_stream_queues` 中无对应 `thread_id` | `async OpenAI(stream=False)`，等待完整响应后返回 |
| **流式** | `_stream_queues` 中有队列 | `async OpenAI(stream=True)`，逐 token 推入 `asyncio.Queue` |

流式模式下，`stream_service.py` 从队列消费 token，拼接为 SSE 事件推送给前端：

```
astream(stream_mode="updates")
  ├── merge_retrieval 完成 → SSE: retrieval_done
  ├── map_reviewer 每完成一条 → SSE: map_progress ({current, total, clause_title})
  ├── map_reviewer 全部完成 → SSE: map_done
  ├── reduce_reviewer 逐 token → SSE: token ({token: "..."})
  └── 图执行结束 → SSE: done
```

### 4.3 条件路由

`_route_from_merge` 根据 `state["clauses"]` 决定下游路径：

```python
if state.get("error"):       return END           # 致命错误，终止
if state.get("clauses"):     return "map_review"   # 有条款 → Map-Reduce
return "single_review"                             # 无条款 → 单次审查
```

这实现了**同一个图处理两种输入模式**（文件上传 vs 文本粘贴），不需要前端判断走不同 API。

### 4.4 Fan-out 并行检索

Dispatcher 输出 `branches=["civil", "labor"]` 后，LangGraph 的路由函数 `_route_from_dispatcher` 返回 `["civil_retriever", "labor_retriever"]`，框架自动对这两个节点做 fan-out 并行。两个 retriever 通过 `_merge_branch_results` reducer 将各自结果合并到 `branch_results`，互不覆盖。

### 4.5 Checkpointer：节点级状态快照

每个节点执行完成后，LangGraph 自动将当前 `WorkflowState` 完整快照写入 checkpointer（PostgreSQL / MemorySaver）：

```
parser 完成 → 快照 1（input + file_path + clauses + contract_name）
dispatcher 完成 → 快照 2（+ contract_type + branches）
civil_retriever 完成 → 快照 3（+ branch_results.civil）
labor_retriever 完成 → 快照 4（+ branch_results.labor，reducer 合并）
merge_retrieval 完成 → 快照 5（+ retrieval_result，branch_results 清空）
map_reviewer 完成 → 快照 6（+ clause_reviews）
reduce_reviewer 完成 → 快照 7（+ review_output）
```

Checkpointer 的价值：

- **失败重试**：若 reduce_reviewer 的 LLM 调用因网络超时失败，RetryPolicy 从快照 6 恢复，无需重新跑 parser / dispatcher / retriever / map_reviewer
- **断点续跑**：长时间运行的审查任务可从中断点恢复
- **审计追踪**：完整记录每一步的中间状态

### 4.6 State Reducer

`WorkflowState` 中有两个字段使用了自定义 reducer：

| 字段 | Reducer | 行为 |
|------|---------|------|
| `branch_results` | `_merge_branch_results` | fan-out 节点结果合并（`{**left, **right}`）；空 `{}` 视为清空信号 |
| `warnings` | `operator.add` | 任意节点追加警告自动累加，无需手动拼接 |

其他字段无自定义 reducer——约定单节点写入（如 `contract_type` 只有 dispatcher 写，`review_output` 只有 reviewer/reduce_reviewer 写），无冲突风险。

---

## 五、Map-Reduce 审查架构

### 5.1 设计动机

传统做法是将整个合同 + 全部法律依据塞入单次 LLM 调用。问题：
- 合同条文 + 法律依据可能轻松超过 8K tokens，长合同直接爆上下文
- LLM 对长文本中间段落的关注度衰减（lost-in-the-middle）
- 无法并行，用户等待时间长

Map-Reduce 将审查拆分为两阶段：

### 5.2 Map 阶段：逐条并行审查

```python
tasks = [_review_one(clause, i) for i, clause in enumerate(clauses)]
clause_reviews = await asyncio.gather(*tasks)
```

所有条款**并行**调用 LLM（`asyncio.gather`），每条条款受严格约束：

- 条款内容截断至 500 字符
- 法律依据截断至 2000 字符（覆盖 3-4 条最相关条文）
- `max_tokens=400`：LLM 只输出简洁的 JSON `{compliant, risks[], suggestion}`
- 单条失败不影响其他条款（`_review_one` 内部 catch → 返回错误标记）

流式模式下，每完成一条条款审查即刻向 SSE 推送 `map_progress` 事件，前端渲染进度条。

### 5.3 Reduce 阶段：汇总完整报告

所有条款审查结果通过 `_format_clause_reviews()` 拼接为结构化摘要，连同完整法律依据送入 Reduce LLM。Reduce 节点拥有完整的全局视角，生成标准五段式报告（审查主体 → 法律分析 → 风险识别 → 修改建议 → 法律依据索引）。

与 Map 阶段的小 token 限制不同，Reduce 阶段给予 LLM 充足的输出空间，允许生成完整的 2000-5000 字的审查报告。

### 5.4 文本输入模式（降级路径）

当 `clauses` 为空（用户直接粘贴文本而非上传文件）时，跳过 Map-Reduce，走原有 `reviewer` 单次审查路径。这种降级保证系统在"无条款结构"场景下仍可工作。

---

## 六、错误处理：三层机制

### 6.1 节点级自动重试：RetryPolicy

LangGraph 的 `RetryPolicy` 为每个 LLM 调用节点配置了自动重试（最多 3 次）：

```python
RetryPolicy(retry_on=(APITimeoutError, RateLimitError,
                       APIConnectionError, InternalServerError),
            max_attempts=3)
```

可恢复异常（网络闪断、限流、5xx）不由节点代码 catch，而是向上抛给 LangGraph 框架层，框架从最近的 checkpoint 恢复状态后重试。Dispatcher 额外配置了 `ValueError` 重试——LLM 偶发输出非 JSON 格式，换一次采样通常能正确输出。

### 6.2 节点内降级：catch + warning

非致命错误（检索返回空、JSON 解析失败）在节点内 catch，降级返回空值 + warning，图继续执行。例如检索器 catch 到 `BadRequestError` 后返回 `{"branch_results": {branch: []}}`，merge 节点生成 `"⚠ XX检索未返回结果"` warning，审查节点仍可用其他分支的检索结果继续工作。

### 6.3 致命终止：Command(goto=END)

以下场景直接终止工作流：

| 场景 | 触发节点 | 示例 |
|------|------|------|
| 领域拒识 | dispatcher | 用户输入刑事问题 |
| API 认证失败 | 任意节点 | API Key 无效 |
| 文件格式不支持 | parser | 上传 .txt 文件 |
| 文件损坏 | parser | docx 二进制损坏 |
| 检索汇聚异常 | merge_retrieval | 桥接数据损坏 |

终止时 error 字段写入 state，`stream_service` 从最终快照读取 error 并在 SSE `done` 事件中返回友好提示。

---

## 七、对话记忆：与 Checkpoint 的分离设计

系统有两套独立的持久化机制，各司其职：

| 维度 | Checkpoint | 对话记忆 |
|------|-----------|---------|
| **存储** | PostgreSQL / MemorySaver | MySQL `conversation_threads` + `conversation_messages` |
| **粒度** | 图节点执行后的完整 WorkflowState | 用户可见的消息对（user + assistant） |
| **用途** | 失败重试、断点续跑 | 多轮追问上下文保持 |
| **生命周期** | 7 天 TTL | 持久保留，用户可主动删除 |

### 7.1 追问跳过检索

首轮对话完整执行检索流程后，`retrieval_result`（assembled_text）随 thread 缓存。同 thread 的追问直接复用已有法律依据，跳过检索阶段，仅重新调用 LLM 生成——极大降低追问延迟和 API 费用。

### 7.2 历史压缩

助手消息通常包含数 KB 的完整审查报告，全部塞入历史会快速耗尽上下文窗口。`_trim_history()` 仅提取"一、直接结论"章节（≤300 字符），其余章节丢弃。历史最多保留 10 轮，防止上下文溢出。

---

## 八、技术选型一览

| 组件 | 选型 | 说明 |
|------|------|------|
| 工作流框架 | **LangGraph** | 条件路由、fan-out 并行、checkpoint、RetryPolicy |
| LLM | **DeepSeek-V3** / Qwen3-235B（硅基流动） | 分类/审查/问答 |
| Embedding | **BAAI/bge-large-zh-v1.5**（硅基流动） | 向量检索，1024 维 |
| Reranker | **BAAI/bge-reranker-v2-m3**（硅基流动） | Cross-encoder 重排序 |
| 向量库 | **Chroma**（本地持久化） | 5 个集合，856 条条文，嵌入式部署 |
| 后端 | **FastAPI** + uvicorn | 异步 HTTP + SSE 流式 |
| 前端 | **Vue 3** + Vite + Element Plus | SPA，SSE fetch 流式渲染 |
| 业务 DB | **MySQL** + SQLAlchemy async | 用户/历史/线程 |
| 缓存 | **Redis** | 会话消息 L1 缓存（30min TTL） |
| Checkpoint | **PostgreSQL** → MemorySaver 降级 | AsyncPostgresSaver，5s 超时降级 |
| 文档解析 | **python-docx** + **pypdf** | 模块顶层导入，消除首次调用冷启动 |

---

## 九、BRANCH_SPEC 扩展

新增法律领域只需在 `BRANCH_SPEC` 中加一条配置，图结构自动适配：

```python
BRANCH_SPEC["consumer"] = {                    # 未来示例：消费者保护
    "priority": 1,
    "label": "消费者保护规范",
    "description": "消费者权益保护法+产品质量法",
    "bridged": [{...}],
    "standalone": [{"collection": "consumer_protection_law", "k": 2}],
    "max_rerank_blocks": 5,
}
```

只需补齐：① Chroma 集合（法律条文的 JSONL → 向量化入库）；② 桥接 JSON；③ dispatcher 关键词列表 + LLM prompt 分类项。`_build_retrieval_layer` 工厂函数自动为新分支生成 retriever 节点和路由规则，图编译无需手动修改。
