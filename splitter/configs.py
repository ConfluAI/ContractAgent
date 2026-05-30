"""
所有法律文档的切分配置。

新增法律只需在此文件加一份 SplitterConfig + 一个 main 入口即可。
"""

from __future__ import annotations

from pathlib import Path
from splitter.engine import SplitterConfig, HeadingLevel, BridgeSpec, cn_to_int

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ═══════════════════════════════════════════════════════════════════════════
# Domain 自定义函数（仅民法典等复杂分类需要）
# ═══════════════════════════════════════════════════════════════════════════

def _civil_domain(ctx: dict) -> str:
    """民法典条文 → domain 标签。"""
    book = ctx.get("book", "") or ""
    chapter = ctx.get("chapter", "") or ""

    if "合同" in book:
        for kw, label in [
            ("买卖", "合同分则"), ("借款", "合同分则"), ("租赁", "合同分则"),
            ("承揽", "合同分则"), ("建设工程", "合同分则"), ("运输", "合同分则"),
            ("技术", "合同分则"), ("保管", "合同分则"), ("仓储", "合同分则"),
            ("委托", "合同分则"), ("物业", "合同分则"), ("行纪", "合同分则"),
            ("中介", "合同分则"), ("合伙", "合同分则"), ("赠与", "合同分则"),
            ("融资租赁", "合同分则"), ("保理", "合同分则"), ("供用电", "合同分则"),
        ]:
            if kw in chapter:
                return label
        if "保证" in chapter:
            return "保证合同"
        if "一般规定" in chapter:
            return "合同通则"
        if "订立" in chapter:
            return "合同订立"
        if "效力" in chapter:
            return "合同效力"
        if "履行" in chapter:
            return "合同履行"
        if "保全" in chapter:
            return "合同保全"
        if "变更" in chapter or "转让" in chapter:
            return "合同变更与转让"
        if "终止" in chapter:
            return "合同终止"
        if "违约" in chapter:
            return "违约责任"
        return "合同通用"
    if "代理" in chapter:
        return "代理"
    if "民事法律行为" in chapter:
        return "民事法律行为"
    if "责任" in chapter:
        return "民事责任"
    return "合同通用"


def _civil_include(ctx: dict) -> bool:
    """民法典：仅保留合同编全部 + 总则编第6/7/8章。"""
    book_num = ctx.get("book_num")
    chapter_num = ctx.get("chapter_num")
    if book_num == 3:
        return True
    if book_num == 1 and chapter_num in {6, 7, 8}:
        return True
    return False


def _labor_law_include(ctx: dict) -> bool:
    """劳动法：仅保留合同相关章节。"""
    return ctx.get("chapter_num") in {3, 4, 5, 7, 9, 10, 12}


def _labor_contract_law_include(ctx: dict) -> bool:
    """劳动合同法：排除第8章附则。"""
    return ctx.get("chapter_num") != 8


def _labor_regulation_include(ctx: dict) -> bool:
    """劳动合同法实施条例：排除第6章附则。"""
    return ctx.get("chapter_num") != 6


# ═══════════════════════════════════════════════════════════════════════════
# 配置清单
# ═══════════════════════════════════════════════════════════════════════════

CIVIL_CODE = SplitterConfig(
    input_path=str(DATA_DIR / "中华人民共和国民法典_20200528.docx"),
    output_path=str(DATA_DIR / "civil_code_contract_chunks.jsonl"),
    source_name="中华人民共和国民法典",
    law_rank=4,
    law_rank_desc="法律",
    heading_levels=[
        HeadingLevel("book", "编",
                      r"^第([一二三四五六七八九十百千]+)编[\s]+(.+)$"),
        HeadingLevel("sub_book", "分编",
                      r"^第([一二三四五六七八九十百千]+)分编[\s]+(.+)$"),
        HeadingLevel("chapter", "章",
                      r"^第([一二三四五六七八九十百千]+)章[\s]+(.+)$"),
        HeadingLevel("section", "节",
                      r"^第([一二三四五六七八九十百千]+)节[\s]+(.+)$"),
    ],
    include_check=_civil_include,
    domain_fn=_civil_domain,
)

JUDICIAL_INTERPRETATION = SplitterConfig(
    input_path=str(DATA_DIR / "最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释_20231204.docx"),
    output_path=str(DATA_DIR / "judicial_interpretation_contract_general.jsonl"),
    source_name="最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释",
    law_rank=4,
    law_rank_desc="司法解释",
    heading_levels=[
        # 司法解释用 "一、一般规定" 格式，无"第X章"前缀
        HeadingLevel("chapter", "",
                      r"^([一二三四五六七八九十]+)、(.+)$"),
    ],
    domain_map={
        1: "合同通则", 2: "合同订立", 3: "合同效力", 4: "合同履行",
        5: "合同保全", 6: "合同变更与转让", 7: "合同终止",
        8: "违约责任", 9: "合同通用",
    },
    bridge=BridgeSpec(
        cite_trigger="民法典第",
        output_path=str(DATA_DIR / "contract_law_bridge.json"),
        key_from_primary="civil_to_interpretation",
        key_to_primary="interpretation_to_civil",
    ),
)

LABOR_LAW = SplitterConfig(
    input_path=str(DATA_DIR / "中华人民共和国劳动法_20181229.docx"),
    output_path=str(DATA_DIR / "labor_law_contract_chunks.jsonl"),
    source_name="中华人民共和国劳动法",
    law_rank=4,
    law_rank_desc="法律",
    heading_levels=[
        HeadingLevel("chapter", "章",
                      r"^第([一二三四五六七八九十]+)章[\s]+(.+)$"),
    ],
    include_check=_labor_law_include,
    domain_map={
        3: "劳动合同", 4: "工作时间与休息休假", 5: "工资",
        7: "特殊保护", 9: "社会保险与福利", 10: "劳动争议", 12: "法律责任",
    },
)

LABOR_CONTRACT_LAW = SplitterConfig(
    input_path=str(DATA_DIR / "中华人民共和国劳动合同法_20121228.docx"),
    output_path=str(DATA_DIR / "labor_contract_law_chunks.jsonl"),
    source_name="中华人民共和国劳动合同法",
    law_rank=4,
    law_rank_desc="法律",
    heading_levels=[
        HeadingLevel("chapter", "章",
                      r"^第([一二三四五六七八九十]+)章[\s]+(.+)$"),
        HeadingLevel("section", "节",
                      r"^第([一二三四五六七八九十]+)节[\s]+(.+)$"),
    ],
    include_check=_labor_contract_law_include,
    domain_map={
        1: "劳动合同总则", 2: "劳动合同订立", 3: "劳动合同履行与变更",
        4: "劳动合同解除与终止", 5: "特别规定",
        6: "监督检查", 7: "法律责任",
    },
)

LABOR_CONTRACT_REGULATION = SplitterConfig(
    input_path=str(DATA_DIR / "中华人民共和国劳动合同法实施条例_20080918.docx"),
    output_path=str(DATA_DIR / "labor_contract_regulation_chunks.jsonl"),
    source_name="中华人民共和国劳动合同法实施条例",
    law_rank=3,
    law_rank_desc="行政法规",
    heading_levels=[
        HeadingLevel("chapter", "章",
                      r"^第([一二三四五六七八九十]+)章[\s]+(.+)$"),
    ],
    include_check=_labor_regulation_include,
    domain_map={
        1: "劳动合同实施总则", 2: "劳动合同订立", 3: "劳动合同解除与终止",
        4: "劳务派遣", 5: "法律责任",
    },
    bridge=BridgeSpec(
        cite_trigger="劳动合同法第",
        output_path=str(DATA_DIR / "labor_contract_law_bridge.json"),
        key_from_primary="labor_contract_law_to_regulation",
        key_to_primary="regulation_to_labor_contract_law",
    ),
)

# ═══════════════════════════════════════════════════════════════════════════
# 批量运行入口
# ═══════════════════════════════════════════════════════════════════════════

ALL_CONFIGS = [
    CIVIL_CODE,
    JUDICIAL_INTERPRETATION,
    LABOR_LAW,
    LABOR_CONTRACT_LAW,
    LABOR_CONTRACT_REGULATION,
]
