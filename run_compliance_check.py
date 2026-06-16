from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.engine import run_pipeline


BASE_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行衍生品交易报告合规审查工作台的规则引擎。"
    )
    parser.add_argument("--input", default="data/processed/trades.json", help="规范化交易数据 trades.json 路径")
    parser.add_argument(
        "--regimes",
        default="CFTC,EMIR",
        help="逗号分隔的监管辖区。默认 CFTC,EMIR；当前产品原型支持 CFTC、EMIR 和 MAS。",
    )
    parser.add_argument(
        "--product-definitions",
        default="data/product_definitions",
        help="ANNA-DSB Product-Definitions 本地目录。",
    )
    parser.add_argument("--output-dir", default="output", help="JSON/CSV 输出目录")
    parser.add_argument("--dashboard-dir", default="dashboard", help="dashboard HTML 输出目录")
    return parser.parse_args()


def project_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return BASE_DIR / path


def product_definitions_ready(path: Path) -> bool:
    return (
        path.exists()
        and (path / "PROD" / "OTC-Products" / "UPI").exists()
        and (path / "PROD" / "OTC-Products" / "codesets").exists()
    )


def resolve_input_path(path: Path) -> Path:
    candidates = [
        path,
        project_path(path),
        BASE_DIR / "data" / "processed" / "trades.json",
        BASE_DIR / "data" / "raw" / "trades.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "未找到交易输入文件。请运行 python tools/prepare_data.py，"
        "或通过 --input /path/to/trades.json 指定路径。"
    )


def resolve_product_definitions(path: Path) -> Path:
    candidates = [
        path,
        project_path(path),
        BASE_DIR / "data" / "product_definitions",
    ]
    for candidate in candidates:
        if product_definitions_ready(candidate):
            return candidate
    raise FileNotFoundError(
        "未找到 ANNA-DSB Product-Definitions。请运行 python tools/prepare_data.py，"
        "或通过 --product-definitions /path/to/product_definitions 指定路径。"
    )


def main() -> int:
    args = parse_args()
    input_path = resolve_input_path(Path(args.input))
    output_dir = project_path(Path(args.output_dir))
    dashboard_dir = project_path(Path(args.dashboard_dir))
    regimes = [item.strip().upper() for item in args.regimes.split(",") if item.strip()]
    product_definitions = resolve_product_definitions(Path(args.product_definitions))

    results = run_pipeline(input_path, product_definitions, regimes, output_dir, dashboard_dir)
    summary = results["summary"]
    print("合规审查引擎运行完成")
    print(f"处理交易数: {results['metadata']['trade_count']}")
    print(f"监管辖区: {', '.join(results['metadata']['regimes'])}")
    print(f"兼容状态统计: {summary['overall_status_counts']}")
    top_counts = summary.get("top_substantive_rule_counts", summary["top_rule_counts"])
    print(f"主要实质规则统计: {dict(list(top_counts.items())[:8])}")
    print(f"已写入: {output_dir / 'compliance_results.json'}")
    print(f"已写入: {output_dir / 'findings.csv'}")
    print(f"已写入: {dashboard_dir / 'dashboard.html'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
