# ContractAgent — 合同审查智能体

基于 LangGraph + RAG 的中国合同法律审查工具。支持 docx/pdf 文件输入，自动识别合同类型，多分支并��检索法律条文，生成结构化审查报告。

## 快速开始

### 环境要求

- Python 3.11+
- 硅基流动 API Key（[注册获取](https://siliconflow.cn)）

### 安装

```bash
git clone https://github.com/CrowdSenseAI/ContractAgent.git
cd ContractAgent

# 安装依赖
pip install -e .
# 或使用 uv
uv sync

# 配置 API Key
cp .env.template .env
# 编辑 .env 填入你的 SILICONFLOW_API_KEY

# 构建向量数据库（约 856 条法律条文）
PYTHONPATH=. python builder/build_vector_store.py
```

### 验证安装

```bash
PYTHONPATH=. python -c "
from graph.workflow import run_contract_review
result = run_contract_review('拖欠工资能否解除劳动合同')
print(result['review_output'][:300])
"
```

## 使用方式

### 1. 审查合同文件（docx / pdf）

```python
from graph.workflow import run_contract_review

# 传入合同文件路径，自动解析文本并审查
result = run_contract_review(file_path="劳动合同.docx")
print(result["contract_type"])   # labor / civil / mixed
print(result["review_output"])   # 结构化审查报告
```

```bash
python graph/workflow.py --file 劳动合同.docx
```

### 2. 审查合同文本

```python
result = run_contract_review(user_input="""
第八条 劳动报酬：甲方有权根据经营状况决定是否发放绩效工资。
第十五条 劳动合同解除：乙方连续两个月业绩考核不合格的，
        甲方可立即解除劳动合同且无需支付经济补偿。
""")
```

```bash
python graph/workflow.py "第八条 甲方有权单方决定是否发放绩效工资..."
```

### 3. 法律问答

```python
result = run_contract_review("公司拖欠工资3个月，员工可否解除合同并要求经济补偿？")
```

```bash
python graph/workflow.py "买方拒付货款，卖方如何主张违约金"
```

### 4. 底层检索（仅查条文，不审查）

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
| 审查主体 | 合同性质、所属法��领域、适用规范 |
| 法律分析 | 逐条分析法律要件，引用具体条文 |
| 风险识别 | 风险点 + 等级（高/中/低） |
| 修改建议 | 具体条款修改方案或法律行动建议 |
| 法律依据索引 | 报告中引用的所有条文号及出处 |

## 工作流

```
docx/pdf → [Parser] → [Dispatcher] → [Retriever] → [Reviewer] → 审查报告
              ↑            ↑               ↑              ↑
         文件→文本     LLM判断类型    多分支并行检索   LLM结构审查
                      labor/civil      + 重排序       风险+建议+条文
```

- **Parser**: 解析 docx/pdf 为纯文本（无文件则透传）
- **Dispatcher**: LLM 分类合同类型（劳动/民事/混合），决定检索分支
- **Retriever**: 5 库并行向量检索 + 1-hop 桥接补全 + LLM 三维度重排序
- **Reviewer**: LLM 生成结构化审查报告，遵循"特别法优于一般法"原则

## 项目结构

```
ContractAgent/
├── config/
│   └── models.py              # 集中式模型路由 (硅基流动)
├── splitter/                  # 数据管线 — 法律文件切分
├── builder/                   # 向量库构建 — JSONL → Chroma
├── retrieval/                 # 检索子系统 — 配置驱动多分支并行
│   ├── retriever.py           # 检索器核心
│   ├── embeddings.py          # BGE Embeddings (硅基流动)
│   └── loaders.py             # JSONL + 桥接文件加载
├── graph/                     # LangGraph 工作流
│   ├── state.py               # WorkflowState 定义
│   ├── parser.py              # docx/pdf 文件解析节点
│   ├── dispatcher.py          # 合同类型分类节点
│   ├── reviewer.py            # 合同审查 LLM 节点
│   └── workflow.py            # 图组装 + 编译 + 运行入口
├── data/                      # 法律条文数据 + 向量库
├── .env.template              # API Key 配置模板
├── ARCHITECTURE.md            # 详细架构文档
└── pyproject.toml
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

