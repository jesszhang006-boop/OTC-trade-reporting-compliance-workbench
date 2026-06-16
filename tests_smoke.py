from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from run_compliance_check import resolve_input_path, resolve_product_definitions
from src.engine import analyze_trades, load_trades, run_pipeline


def run_results(regimes: list[str]) -> dict:
    with TemporaryDirectory(prefix="regtech_smoke_") as tmp:
        tmp_root = Path(tmp)
        return run_pipeline(
            resolve_input_path(Path("data/processed/trades.json")),
            resolve_product_definitions(Path("data/product_definitions")),
            regimes,
            tmp_root / "output",
            tmp_root / "dashboard",
        )


def test_key_regtech_cases() -> None:
    results = run_results(["CFTC", "MAS"])
    by_id = {row["trade_id"]: row for row in results["trades"]}
    assert results["metadata"]["trade_count"] == 28
    assert by_id["T005"]["overall_status"] == "WARNING"
    assert any(item["rule_id"] == "LIBOR_WARNING" for item in by_id["T005"]["findings"])
    assert by_id["T008"]["upi"]["codeset_results"]["notional_currency"]["status"] == "VALID"
    assert by_id["T013"]["parse"]["engine_parse_status"] == "PARTIAL"
    assert any(item["rule_id"] == "MAS_NULL_MARGIN" for item in by_id["T017"]["findings"])
    assert by_id["T026"]["upi"]["upi_status"] == "NO_PRODUCT_DEFINITION"
    assert by_id["T027"]["overall_status"] == "NOT_REPORTABLE"
    assert by_id["T027"]["data_quality_status"] == "NONCOMPLIANT"
    assert by_id["T027"]["reporting_scope_status"] == "OUT_OF_SCOPE"
    assert by_id["T027"]["regulatory_conclusion"] == "NOT_REPORTABLE_EVENT_CONTRACT"
    assert by_id["T027"]["economic_function_test"]["engine_conclusion"] == "NOT_REPORTABLE_EVENT_CONTRACT"
    assert by_id["T027"]["supervisory_flags"]["recommended_cftc_action"] == "EC1_REVIEW_BELOW_PROPOSED_THRESHOLD"
    assert by_id["T028"]["classification_conclusion"] == "CONDITIONAL_EVENT_CONTRACT"
    assert "schema_proposal" in results["event_contract_analysis"]
    assert "MAS_SG_NEXUS" not in results["summary"]["top_compliance_rule_counts"]


def test_emir_display_regime() -> None:
    results = run_results(["CFTC", "EMIR"])
    by_id = {row["trade_id"]: row for row in results["trades"]}
    mas_results = run_results(["CFTC", "MAS"])
    mas_by_id = {row["trade_id"]: row for row in mas_results["trades"]}
    assert results["metadata"]["trade_count"] == 28
    assert by_id["T013"]["parse"]["engine_parse_status"] == "PARTIAL"
    assert all(by_id[trade_id]["upi"]["upi_status"] == "NO_PRODUCT_DEFINITION" for trade_id in ["T026", "T027", "T028"])
    assert any(item["rule_id"] == "EMIR_NULL_MARGIN" for item in by_id["T017"]["findings"])
    assert any(item["rule_id"] == "MAS_NULL_MARGIN" for item in mas_by_id["T017"]["findings"])
    assert by_id["T026"]["supervisory_flags"]["recommended_cftc_action"] == "PART45_DCM_EVENT_REPORTING_CANDIDATE"
    assert not any(item["rule_id"] == "REGIME_UNSUPPORTED" and item["regime"] == "EMIR" for row in results["trades"] for item in row["findings"])


def test_additional_report_test_cases() -> None:
    product_definitions = resolve_product_definitions(Path("data/product_definitions"))
    base_trades = load_trades(resolve_input_path(Path("data/processed/trades.json")))
    base_by_id = {row["trade_id"]: row for row in base_trades}

    at004 = deepcopy(base_by_id["T002"])
    at004["trade_id"] = "AT004"
    at004["uti"] = "5493001KJTIIGC8Y1R1220250103TRDAT004"
    at004["other_counterparty_lei"] = "XKZZ2JZF41MRHTR1V494"

    at005 = deepcopy(base_by_id["T014"])
    at005["trade_id"] = "AT005"
    at005["asset_class"] = "Credit"
    at005["instrument_type"] = "CreditDefaultSwap"
    at005["use_case"] = "Index"
    at005["uti"] = "5493001KJTIIGC8Y1R1220251001TRDAT005"
    at005["booked_in_sg"] = True
    at005["traded_in_sg"] = True
    at005["initial_margin_posted"] = None
    at005["variation_margin_posted"] = None
    at005["collateral_margin_posted"] = None

    results = analyze_trades([at004, at005], product_definitions, ["CFTC", "MAS"])
    by_id = {row["trade_id"]: row for row in results["trades"]}
    assert any(item["rule_id"] == "LEI_CHECK_DIGIT" for item in by_id["AT004"]["findings"])
    assert any(item["rule_id"] == "MAS_NULL_MARGIN" for item in by_id["AT005"]["findings"])


def test_no_external_project_fallback() -> None:
    external_fallback_name = "H" + "W" + "2_test1"
    for path in [
        Path("run_compliance_check.py"),
        Path("tools/prepare_data.py"),
        Path("tools") / ("data_" + "audit.py"),
        Path("src/engine.py"),
    ]:
        if path.exists():
            assert external_fallback_name not in path.read_text(encoding="utf-8")


def test_display_surface_uses_current_author_and_no_document_chain() -> None:
    root = Path(__file__).resolve().parent
    display_files = [
        "README.md",
        "run_compliance_check.py",
        "tools/prepare_data.py",
        "src/engine.py",
        "src/models.py",
        "data/README.md",
        "data/data_manifest.json",
        "dashboard/dashboard.html",
    ]
    combined = "\n".join((root / path).read_text(encoding="utf-8") for path in display_files)
    for required in [
        "衍生品交易报告合规审查工作台",
        "个人 RegTech 产品原型",
        "产品路线图",
        "张钧诒",
        "Zhang Junyi",
        "compliance_results.json",
        "ComplianceResults",
    ]:
        assert required in combined

    old_author_zh = "张" + "俊义"
    old_author_en = "Junyi " + "Zhang"
    old_written_artifact = "written_" + "report"
    old_build_script = "build_" + "report"
    old_cover_script = "build_" + "cover_page"
    old_contents_script = "build_" + "contents_page"
    old_format_script = "format_" + "report_docx"
    old_refine_script = "refine_" + "report_layout"
    old_audit_name = "data_" + "audit"
    old_results_name = "compliance_" + "report.json"
    banned_terms = [
        old_author_zh,
        old_author_en,
        "监管分析" + "白皮书",
        old_written_artifact,
        old_build_script,
        old_cover_script,
        old_contents_script,
        old_format_script,
        old_refine_script,
        old_audit_name,
        old_results_name,
        "Home" + "work",
        "home" + "work",
        "H" + "W" + "2",
        "assign" + "ment",
        "sub" + "mission",
        "teach" + "er",
        "starter " + "notebook",
        "Represented " + "by",
        "A-" + "Version",
        "Report " + "Representative",
    ]
    for term in banned_terms:
        assert term not in combined

    removed_paths = [
        "reports",
        "tmp/pdfs",
        "dashboard" + "_demo",
        "output" + "_demo",
        f"tools/{old_build_script}.py",
        f"tools/{old_cover_script}.py",
        f"tools/{old_contents_script}.py",
        f"tools/{old_format_script}.py",
        f"tools/{old_refine_script}.py",
        f"tools/{old_audit_name}.py",
    ]
    for path in removed_paths:
        assert not (root / path).exists()


def test_dashboard_supports_chinese_english_toggle() -> None:
    old_author_zh = "张" + "俊义"
    old_author_en = "Junyi " + "Zhang"
    old_results_name = "compliance_" + "report.json"
    with TemporaryDirectory(prefix="regtech_dashboard_i18n_") as tmp:
        tmp_root = Path(tmp)
        run_pipeline(
            resolve_input_path(Path("data/processed/trades.json")),
            resolve_product_definitions(Path("data/product_definitions")),
            ["CFTC", "EMIR"],
            tmp_root / "output",
            tmp_root / "dashboard",
        )
        dashboard_html = (tmp_root / "dashboard" / "dashboard.html").read_text(encoding="utf-8")
        heatmap_html = (tmp_root / "dashboard" / "pages" / "compliance_heatmap.html").read_text(encoding="utf-8")
        assert (tmp_root / "output" / "compliance_results.json").exists()
        assert not (tmp_root / "output" / old_results_name).exists()

    assert "Derivatives Trade Reporting Compliance Review Workbench" in dashboard_html
    assert "张钧诒" in dashboard_html
    assert "Zhang Junyi" in dashboard_html
    assert old_author_zh not in dashboard_html
    assert old_author_en not in dashboard_html
    assert "Compliance Heatmap" in heatmap_html

    for html_text in [dashboard_html, heatmap_html]:
        assert 'class="language-toggle"' in html_text
        assert 'data-lang-target="zh"' in html_text
        assert 'data-lang-target="en"' in html_text
        assert "localStorage" in html_text


if __name__ == "__main__":
    test_key_regtech_cases()
    test_emir_display_regime()
    test_additional_report_test_cases()
    test_no_external_project_fallback()
    test_display_surface_uses_current_author_and_no_document_chain()
    test_dashboard_supports_chinese_english_toggle()
    print("Smoke tests passed")
