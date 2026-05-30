"""
一键运行所有切分任务。

用法:
  python -m splitter.run            # 全部
  python -m splitter.run civil      # 仅民法典
  python -m splitter.run labor      # 劳动法系列
"""

import sys

from splitter.engine import DocxSplitter
from splitter.configs import ALL_CONFIGS, CIVIL_CODE, JUDICIAL_INTERPRETATION, \
    LABOR_LAW, LABOR_CONTRACT_LAW, LABOR_CONTRACT_REGULATION

CONFIG_MAP = {
    "civil":       [CIVIL_CODE],
    "judicial":    [JUDICIAL_INTERPRETATION],
    "labor_law":   [LABOR_LAW],
    "labor_contract": [LABOR_CONTRACT_LAW],
    "labor_regulation": [LABOR_CONTRACT_REGULATION],
    "labor":       [LABOR_LAW, LABOR_CONTRACT_LAW, LABOR_CONTRACT_REGULATION],
    "all":         ALL_CONFIGS,
}


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else "all"
    configs = CONFIG_MAP.get(key)
    if configs is None:
        print(f"Unknown target: {key}", file=sys.stderr)
        print(f"Available: {', '.join(CONFIG_MAP)}", file=sys.stderr)
        sys.exit(1)

    for cfg in configs:
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"  {cfg.source_name}", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        DocxSplitter(cfg).run()


if __name__ == "__main__":
    main()
