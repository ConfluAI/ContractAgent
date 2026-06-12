# ContractAgent — 合同审查智能体

基于 LangGraph + RAG 的中国合同法律审查工具。支持 docx/pdf 文件输入，自动识别合同类型，多分支并行检索法律条文，生成结构化审查报告。提供 Web UI 和 Python API 两种使用方式。

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+（前端）
- MySQL 8.0+、PostgreSQL、Redis（后端服务）
- 硅基流动 API Key（[注册获取](https://siliconflow.cn)）

### 安装

```bash
git clone https://github.com/ConfluAI/ContractAgent.git
cd ContractAgent

# 安装 Python 依赖
pip install -e .
# 或使用 uv
uv sync

# 配置环境变量
cp .env.template .env
# 编辑 .env 填入 SILICONFLOW_API_KEY 及数据库连接信息

# 构建向量数据库（约 856 条法律条文）
PYTHONPATH=. python builder/build_vector_store.py

# 安装前端依赖
cd frontend && npm install && cd ..
```

### 数据库初始化

需要 MySQL、PostgreSQL、Redis 三个外部服务。数据库表由 SQLAlchemy 自动创建，首次启动后端即可。

### 一键启动

```bash
# Windows
start.bat

# 或手动启动
python run_server.py          # 后端 :8000
cd frontend && npm run dev    # 前端 :5173
```

浏览器访问 [http://localhost:5173](http://localhost:5173)，注册账号后登录使用。

## 使用方式

### 1. Web UI（推荐）

- **合同审查**：上传 docx/pdf 文件或粘贴合同文本，流式生成结构化审查报告
- **法律咨询**：多轮对话式法律问答，支持追问和上下文保持
- **查询历史**：查看和回顾历史审查记录
- **用户管理**（管理员）：角色管理、用户增删

### 2. Python API

```python
from graph.workflow import run_contract_review

# 审查合同文件
result = run_contract_review(file_path="劳动合同.docx")
print(result["contract_type"])   # labor / civil / mixed
print(result["review_output"])   # 结构化审查报告

# 审查合同文本
result = run_contract_review(user_input="第八条 甲方有权单方决定是否发放绩效工资...")

# 法律问答
result = run_contract_review("公司拖欠工资3个月，员工可否解除合同并要求经济补偿？")
```

```bash
# 命令行
python graph/workflow.py --file 劳动合同.docx
python graph/workflow.py "买方拒付货款，卖方如何主张违约金"
```

### 3. REST API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/register` | POST | 用户注册 |
| `/api/auth/login` | POST | 登录获取 JWT |
| `/api/auth/me` | GET | 当前用户信息 |
| `/api/review/stream` | POST | 流式合同审查（SSE） |
| `/api/qa/stream` | POST | 流式法律问答（SSE） |
| `/api/upload/stream` | POST | 流式文件审查（SSE） |
| `/api/history` | GET | 查询历史 |
| `/api/threads` | GET | 对话线程列表 |
| `/api/users` | GET | 用户列表（admin） |

### 4. 底层检索（仅查条文）

```python
from retrieval.retriever import ContractRetriever

r = ContractRetriever()
result = r.search("违约金过高如何调整", branches=["civil"])
print(result["assembled_text"])
```

## 审查报告结构

每份审查报告包含五个部分：

| 章节 | 内容 |
|------|------|
| 审查主体 | 合同性质、所属法律领域、适用规范 |
| 法律分析 | 逐条分析法律要件，引用具体条文 |
| 风险识别 | 风险点 + 等级（高/中/低） |
| 修改建议 | 具体条款修改方案或法律行动建议 |
| 法律依据索引 | 报告中引用的所有条文号及出处 |

## 架构

```
┌──────────────┐     ┌──────────────────────────────┐
│  Vue 3 前端   │────▶│  FastAPI 后端 (:8000)          │
│  Element Plus │     │                              │
│  Vite (:5173) │     │  ┌────────────────────────┐  │
└──────────────┘     │  │  LangGraph 工作流        │  │
                     │  │  Parser → Dispatcher     │  │
                     │  │  → Retriever → Reviewer  │  │
                     │  └────────────────────────┘  │
                     │         │         │          │
                     │    ┌────▼───┐ ┌──▼────┐     │
                     │    │ MySQL  │ │Chroma │     │
                     │    │ 用户/   │ │向量库  │     │
                     │    │ 历史/   │ │5个集合 │     │
                     │    │ 线程   │ │       │     │
                     │    └────────┘ └───────┘     │
                     │    ┌────────┐ ┌──────────┐  │
                     │    │  Redis  │ │PostgreSQL│  │
                     │    │ 消息缓存 │ │Checkpoint│  │
                     │    └────────┘ └──────────┘  │
                     └──────────────────────────────┘
```

- **Parser**: 解析 docx/pdf 为纯文本（无文件则透传）
- **Dispatcher**: LLM 分类合同类型（劳动/民事/混合），决定检索分支
- **Retriever**: 5 库并行向量检索 + 1-hop 桥接补全 + LLM 三维度重排序
- **Reviewer**: LLM 生成结构化审查报告，遵循"特别法优于一般法"原则

### 数据存储

| 存储 | 用途 |
|------|------|
| MySQL | 用户、查询历史、对话线程、消息 |
| PostgreSQL | LangGraph checkpoint 持久化（7天自动清理） |
| Redis | 会话消息 L1 缓存（30 分钟 TTL） |
| Chroma | 法律条文向量嵌入（5 个集合，856 条） |

## 项目结构

```
ContractAgent/
├── server/                     # FastAPI 后端
│   ├── main.py                 # 应用入口、CORS、路由注册
│   ├── config.py               # 配置管理（Pydantic Settings）
│   ├── database.py             # SQLAlchemy 异步引擎
│   ├── redis_client.py         # Redis 客户端
│   ├── auth/                   # JWT 认证 + 权限依赖
│   ├── models/                 # SQLAlchemy ORM 模型
│   ├── schemas/                # Pydantic 请求/响应模型
│   ├── routers/                # API 路由（auth/users/review/history/threads）
│   └── services/               # 业务逻辑 + SSE 流式服务 + 缓存 + 清理
├── frontend/                   # Vue 3 前端
│   └── src/
│       ├── router/             # 路由（按角色分离 admin/user）
│       ├── stores/             # Pinia 认证状态管理
│       ├── api/                # Axios HTTP 客户端 + SSE
│       ├── layouts/            # Dashboard 布局（侧边栏 + 顶栏）
│       ├── components/         # 审查/问答/历史页面组件
│       └── views/              # 登录/注册/管理页面
├── graph/                      # LangGraph 工作流
│   ├── state.py                # WorkflowState 定义
│   ├── parser.py               # docx/pdf 解析节点
│   ├── dispatcher.py           # 合同类型分类节点
│   ├── reviewer.py             # 审查 LLM 节点（流式/阻塞）
│   ├── qa_responder.py         # 问答 LLM 节点
│   └── workflow.py             # 图组装 + 编译 + 运行入口
├── retrieval/                  # RAG 检索子系统
│   ├── retriever.py            # 多分支并行检索 + 重排序
│   ├── embeddings.py           # BGE Embeddings（硅基流动）
│   └── loaders.py              # JSONL + 桥接文件加载
├── builder/                    # 向量库构建 — JSONL → Chroma
├── splitter/                   # 法律文件切分管线
├── config/models.py            # 集中式模型路由（LLM/Embedding/Rerank）
├── data/                       # 法律条文 + Chroma 向量库
├── run_server.py               # 后端启动入口
├── start.bat                   # Windows 一键启动脚本
├── pyproject.toml
└── .env.template
```

## 法律数据库

| 数据库 | 条文数 | 位阶 |
|--------|:-----:|:----:|
| 民法典（合同编 + 总则3章） | 581 | 法律 |
| 合同编通则司法解释 | 69 | 司法解释 |
| 劳动法（合同相关7章） | 76 | 法律 |
| 劳动合同法（排除附则） | 95 | 法律 |
| 劳动合同法实施条例 | 35 | 行政法规 |
| **总计** | **856** | |
