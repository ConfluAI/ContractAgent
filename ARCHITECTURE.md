# ContractAgent — 合同审查智能体 · 检索子系统

> **版本**: `retrieval-subsystem-v1`  
> **定位**: 法律知识库 + 多分支并行检索，为下游合同审查 LLM 提供精准的条文依据

---

## 快速开始

### 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器
- 硅基流动 API Key（[注册获取](https://siliconflow.cn)）

### 安装与初始化

```bash
# 1. 克隆仓库
git clone https://github.com/CrowdSenseAI/ContractAgent.git
cd ContractAgent

# 2. 安装依赖
uv sync

# 3. 配置 API Key（在项目根目录创建 .env 文件）
echo 'SILICONFLOW_API_KEY=你的密钥' > .env

# 4. 构建向量数据库（从 JSONL 生成 Chroma，约 856 条向量）
uv run python build_vector_store.py
```

### 快速验证

```bash
uv run python -c "
from retriever import ContractRetriever
r = ContractRetriever()

# 测试民事合同查询
result = r.search('买方拒付货款可否解除合同', branches=['civil'])
print(result['assembled_text'][:500])

# 测试劳动合同查询
result = r.search('公司拖欠工资能否直接解除合同', branches=['labor', 'civil'])
print(result['assembled_text'][:500])
"
```

### 切分自己的法律文件（可选）

如果你有新的 .docx 格式法律文件需要入库：

```bash
# 参考已有切分脚本编写你自己的 split_xxx.py，然后：
uv run python split_xxx.py              # 生成 JSONL
uv run python build_vector_store.py     # 入库
```

---

## 一、数据管线

```
  .docx 源文件                             拆分脚本                             输出
 ─────────────────────────────────────────────────────────────────────────────

 中华人民共和国民法典          ═══ split_civil_code.py       ═══ civil_code_contract_chunks.jsonl
 (合同编 + 总则3章)                章节 / 条号 / 编章识别            581 条 · 法律(4)

 合同编通则司法解释            ═══ split_judicial_interpretation ═══ judicial_interpretation_contract_general.jsonl
 (全文 69 条)                     .py + 民法典引用提取               69 条 · 司法解释(4)
                                 └─→ contract_law_bridge.json (44 条引用, 30↔32 双向链接)

 中华人民共和国劳动法          ═══ split_labor_law.py        ═══ labor_law_contract_chunks.jsonl
 (合同相关 7 章)                  章节过滤 / 条号识别               76 条 · 法律(4)

 中华人民共和国劳动合同法       ═══ split_labor_contract_law  ═══ labor_contract_law_chunks.jsonl
 (排除附则)                       .py + 节段识别                   95 条 · 法律(4)

 劳动合同法实施条例            ═══ split_labor_contract_reg   ═══ labor_contract_regulation_chunks.jsonl
 (排除附则)                       .py + 劳动合同法引用提取          35 条 · 行政法规(3)
                                 └─→ labor_contract_law_bridge.json (21 条引用, 14↔18 双向链接)

                                         总计: 856 条法律条文
```

### 条文数据格式

每条条文包含两部分：

| 字段 | 说明 | 示例 |
|------|------|------|
| `page_content` | 带层级前缀的条文全文 | `中华人民共和国民法典\n第三编 合同\n第八章 违约责任\n第五百三十三条 ...` |
| `metadata` | 结构化元数据 | `source, section_id, article_num, chapter, law_rank, domain` |

### 法律位阶

```
宪法 (5)  >  法律 (4)  =  司法解释 (4)  >  行政法规 (3)  >  地方法规 (2)  >  规章 (1)
```

---

## 二、向量存储

```
build_vector_store.py
        │
        ├── 读取 5 个 JSONL 文件
        │
        ├── BAAI/bge-large-zh-v1.5 (免费, 1024 维, 硅基流动 API)
        │
        └── 写入 data/chroma_civil_code/

   ┌──────────────────────────────────────────────────────┐
   │  Chroma 持久化目录                                    │
   │                                                      │
   │   Collection              向量数     类型              │
   │  ─────────────────────────────────────────────────    │
   │   civil_code               581      法律               │
   │   judicial_interpretation   69      司法解释            │
   │   labor_law                 76      法律               │
   │   labor_contract_law        95      法律               │
   │   labor_contract_regulation  35      行政法规            │
   │                                                      │
   │   总计                     856                        │
   └──────────────────────────────────────────────────────┘
```

> ⚠️ 向量数据库是二进制文件，**不入 git**。clone 后需本地 `build_vector_store.py` 构建。

---

## 三、检索管线

```
                           ┌──────────┐
                           │  用户输入  │
                           │ 问题/合同  │
                           └─────┬────┘
                                 │
                                 ▼
                      ┌──────────────────┐
                      │ LangGraph Dispatcher │  ← 上游 LLM 判断合同类型
                      └─────────┬────────────┘
                                │
                         branches 参数
                    ["labor","civil"] 或 ["civil"]
                                │
             ┌──────────────────┴──────────────────┐
             │                                     │
             ▼                                     ▼
   ┌──────────────────┐                 ┌──────────────────┐
   │  LABOR BRANCH    │                 │  CIVIL BRANCH    │
   │  优先度 1         │                 │  优先度 2         │
   │  劳动法律规范      │                 │  合同通用规范      │
   └────────┬─────────┘                 └────────┬─────────┘
            │                                    │
   ┌────────┼────────┐              ┌────────────┼────────────┐
   │        │        │              │            │            │
   ▼        ▼        ▼              ▼            ▼            ▼
 劳动合同法  实施条例   劳动法        民法典        司法解释
 (Top 3)  (Top 3)  (Top 2)       (Top 2)      (Top 2)
   │        │        │              │            │
   └──┬─────┘        │              └─────┬──────┘
      │ 1-hop 桥接    │                    │ 1-hop 桥接
      ▼              │                    ▼
   ┌──────┐          │              ┌──────────┐
   │法条-条例│         │              │ 法条-解释  │
   │ 配对   │         │              │  配对     │
   └───┬───┘         │              └─────┬─────┘
       └──────┬───────┘                    │
              │                            │
              ▼                            ▼
         ┌────────┐                  ┌────────┐
         │  去重   │                  │  去重   │
         │条号元组 │                  │条号元组 │
         └───┬────┘                  └───┬────┘
             │                           │
             ▼                           ▼
         ┌────────┐                  ┌────────┐
         │知识块组装│                 │知识块组装│
         │出处+原文│                 │出处+原文│
         │  +标签  │                 │  +标签  │
         └───┬────┘                  └───┬────┘
             │                           │
             ▼                           ▼
      ┌──────────────┐           ┌──────────────┐
      │  LLM RERANK  │           │  LLM RERANK  │
      │  DeepSeek-V3 │           │  DeepSeek-V3 │
      │              │           │              │
      │ 适用性 (1-5)  │           │ 适用性 (1-5)  │
      │ 完整性 (1-5)  │           │ 完整性 (1-5)  │
      │ 互补性 (1-5)  │           │ 互补性 (1-5)  │
      │ temp = 0     │           │ temp = 0     │
      │ 独立平等竞争   │           │              │
      └───────┬──────┘           └───────┬──────┘
              │                          │
              ▼                          ▼
              └──────────┬───────────────┘
                         │
                         ▼
                  ┌────────────┐
                  │   输出组装   │
                  │ 按优先度排列  │
                  │ 分区+出处+评分│
                  └──────┬─────┘
                         │
                         ▼
                  ┌─────────────────────────────────┐
                  │        assembled_text           │
                  │                                 │
                  │  =============================== │
                  │  【第一优先级：劳动法律规范】       │
                  │  知识单元 A ...                  │
                  │  >> 评分: 适用性=5 完整性=4 ...    │
                  │                                 │
                  │  【第二优先级：合同通用规范】       │
                  │  知识单元 A ...                  │
                  │  >> 评分: ...                   │
                  └──────────────┬──────────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │        下游审查 LLM            │
                  │                              │
                  │  "你将收到来自劳动法体系        │
                  │   和民法典体系的法律依据。       │
                  │   特别法优于一般法。"            │
                  └──────────────────────────────┘
```

### Rerank 评分维度

| 维度 | 范围 | 说明 |
|------|:----:|------|
| **适用性** | 1-5 | 条文是否直接规定了问题的核心法律要件 |
| **完整性** | 1-5 | 法条+下位法是否提供可操作的审查步骤 |
| **互补性** | 1-5 | 下位法是否精确补充上位法未明确的要点 |

> 独立条文（无配对）的互补性固定为 1，但 Prompt 明确告知 LLM 不应因此压低排名。

---

## 四、配置驱动 · 加新领域零代码改动

```python
# retriever.py — BRANCH_SPEC
BRANCH_SPEC = {
    "civil":  { priority:2,  bridged:[{civil_code ↔ interpretation}],  standalone:[]      },
    "labor":  { priority:1,  bridged:[{contract_law ↔ regulation}],    standalone:[劳动法]  },
}
```

> 加一个"租赁法"：
> ```python
> "lease": { priority:1, bridged:[{lease_law ↔ lease_regulation}], standalone:[] }
> ```
> 然后 `r.search(q, branches=["lease","civil"])` — **代码其他部分零改动**。

---

## 五、调用方式

```python
from retriever import ContractRetriever
r = ContractRetriever()

# 劳动合同 → 劳动优先 + 民法典参照
result = r.search("拖欠工资能否直接解除合同", branches=["labor", "civil"])

# 纯民事 → 民法典独立运行（召回量自动放大）
result = r.search("货款纠纷如何主张违约金", branches=["civil"])

# 未来多领域 → 按需组合
result = r.search("租房押金不退怎么办", branches=["lease", "civil"])
```

| 场景 | branches | 劳动分支 | 民事分支 |
|------|----------|:------:|:------:|
| 劳动合同审查 | `["labor", "civil"]` | 5 条（优先） | 3 条（参照适用） |
| 民事合同审查 | `["civil"]` | 跳过 | 4 条（直接适用） |
| 未知/混合 | `["labor", "civil"]` | 兜底 | 兜底 |

---

## 六、法律体系关系

```
                     ┌──────────────┐
                     │  宪法 (5)     │
                     └───────┬──────┘
                             │
           ┌─────────────────┼────────────────┐
           │                                  │
           ▼                                  ▼
   ┌──────────────┐                  ┌──────────────┐
   │  民法典 (4)   │                  │  劳动法 (4)   │
   │  合同编+总则  │                  │  母法/一般法   │
   │  581 条      │                  │  76 条        │
   └───────┬──────┘                  └───────┬──────┘
           │ 桥接                            │ 一般法→特别法
           │                                 │ (不建桥，语义补位)
           ▼                                 ▼
   ┌──────────────┐                  ┌──────────────┐
   │ 合同编解释 (4)│                  │ 劳动合同法 (4)│
   │ 69 条        │                  │ 特别法        │
   └──────────────┘                  │ 95 条         │
                                     └───────┬──────┘
                                             │ 桥接
                                             ▼
                                     ┌──────────────┐
                                     │ 实施条例 (3)  │
                                     │ 行政法规      │
                                     │ 35 条         │
                                     └──────────────┘

  劳动关系: 劳动合同法 > 劳动法 >> 民法典 (参照适用)
  民事关系: 民法典 > 司法解释         (直接适用)
```

---

## 项目结构

```
ContractAgent/
├── config/
│   └── models.py              # 集中式模型路由 (硅基流动)
├── utils/
│   ├── __init__.py            # JSONL 加载 + 桥接文件加载
│   └── retrieval.py           # BGE Embeddings 封装
├── split_civil_code.py        # 民法典切分
├── split_judicial_interpretation.py  # 合同编解释切分 + 桥接
├── split_labor_law.py         # 劳动法切分
├── split_labor_contract_law.py      # 劳动合同法切分
├── split_labor_contract_regulation.py  # 实施条例切分 + 桥接
├── build_vector_store.py      # JSONL → Chroma 入库
├── retriever.py               # 检索器核心 (配置驱动)
├── data/
│   ├── *_chunks.jsonl         # 结构化的法律条文
│   ├── *_bridge.json          # 双向桥接文件
│   └── chroma_civil_code/     # ⚠️ 不入 git，需本地构建
├── ARCHITECTURE.md            # 本文档
├── pyproject.toml
└── uv.lock
```
