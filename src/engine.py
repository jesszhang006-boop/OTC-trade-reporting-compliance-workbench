from __future__ import annotations

import csv
import html
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


CONVENTIONAL_ASSET_CLASSES = {"Rates", "Credit", "FX", "Equity", "Commodities"}
EVENT_ASSET_CLASS = "EventContract"

SEVERITY_RANK = {"INFO": 0, "WARNING": 1, "NONCOMPLIANT": 2}

TIMESTAMP_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LEI_RE = re.compile(r"^[A-Z0-9]{20}$")
UTI_SUFFIX_RE = re.compile(r"^[A-Z0-9-]{1,32}$")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ALIAS_CONFIG = PROJECT_ROOT / "config" / "product_aliases.json"


def load_product_aliases(path: Path) -> dict[tuple[str, str, str], tuple[str, str, str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    aliases: dict[tuple[str, str, str], tuple[str, str, str, str]] = {}
    for item in payload:
        source = item["source"]
        target = item["target"]
        aliases[
            (
                source["asset_class"],
                source["instrument_type"],
                source["use_case"],
            )
        ] = (
            target["asset_class"],
            target["instrument_type"],
            target["use_case"],
            item["note"],
        )
    return aliases


PRODUCT_ALIASES = load_product_aliases(PRODUCT_ALIAS_CONFIG)

REGIME_RULES = {
    "CFTC": {
        "required_fields": [
            "uti",
            "upi",
            "reporting_counterparty_lei",
            "other_counterparty_lei",
            "timestamp",
            "notional_currency",
            "action_type",
            "cleared",
        ]
    },
    "MAS": {
        "required_fields": [
            "uti",
            "upi",
            "reporting_counterparty_lei",
            "other_counterparty_lei",
            "timestamp",
            "notional_currency",
            "action_type",
            "cleared",
            "collateral_portfolio_code",
        ]
    },
    "EMIR": {
        "required_fields": [
            "uti",
            "upi",
            "reporting_counterparty_lei",
            "other_counterparty_lei",
            "timestamp",
            "notional_currency",
            "action_type",
            "cleared",
            "collateral_portfolio_code",
        ]
    },
}

SCOPE_FINDING = "SCOPE"
COMPLIANCE_FINDING = "COMPLIANCE"
ALLOWED_ACTION_TYPES = {"NEWT", "MODI", "CORR", "TERM", "EROR", "VALU", "MARU"}

DSB_REQUIRED_FIELD_MAP = {
    "Header.AssetClass": "asset_class",
    "Header.InstrumentType": "instrument_type",
    "Header.UseCase": "use_case",
    "Identifier.UPI": "upi",
    "Attributes.NotionalCurrency": "notional_currency",
    "Attributes.OtherNotionalCurrency": "other_notional_currency",
    "Attributes.ReferenceRate": "reference_rate",
    "Attributes.NotionalSchedule": "notional_amount",
    "Attributes.OptionType": "use_case",
    "Attributes.OptionExerciseStyle": "use_case",
    "Attributes.BaseProduct": "use_case",
    "Attributes.ReturnorPayoutTrigger": "use_case",
}

CFTC_EC1_NOTIFICATION_THRESHOLD_USD = 100_000

EVENT_CONTRACT_UPI_SCHEMA = {
    "TemplateVersion": "1.0",
    "Header": {
        "AssetClass": "EventContract",
        "InstrumentType": "BinaryContract",
        "UseCase": "PoliticalOutcome",
        "Level": "Unique Product Identifier (UPI)",
        "Identifier": {"UPI": "PENDING_ISSUANCE"},
        "Status": "PROPOSED",
        "LastUpdateDateTime": "2026-05-11T00:00:00Z",
    },
    "Attributes": {
        "EventCategory": {
            "Description": "Category of the reference event that determines settlement",
            "AllowedValues": [
                "PoliticalOutcome",
                "MacroeconomicIndicator",
                "RegulatoryDecision",
                "WeatherOrClimate",
                "CorporateAction",
                "LitigationOutcome",
                "Other",
            ],
            "Required": True,
        },
        "ReferenceEntity": {
            "Description": "Body or index whose decision or outcome defines the event",
            "Example": "German Federal Election Commission | US Bureau of Labor Statistics | ESMA",
            "Required": True,
        },
        "EventJurisdiction": {
            "Description": "ISO 3166-1 alpha-2 country code of the primary jurisdiction",
            "Example": "DE | US | EU",
            "Required": True,
        },
        "EventDate": {
            "Description": "Expected event determination date in ISO 8601 format",
            "Example": "2025-09-28",
            "Required": True,
        },
        "ResolutionSource": {
            "Description": "Official authoritative source used to determine final settlement outcome",
            "Example": "Official federal election results | BLS CPI release | ESMA register",
            "Required": True,
        },
        "PayoutType": {
            "Description": "Payout structure at settlement",
            "AllowedValues": ["Binary", "Scalar", "Capped", "Floored", "MultiOutcome"],
            "Required": True,
        },
        "SettlementCurrency": {
            "Description": "Settlement currency: ISO 4217 fiat or stablecoin identifier",
            "Note": "Stablecoin codes such as USDC are not ISO 4217 and require a supplemental identifier scheme.",
            "Required": True,
        },
        "PlatformType": {
            "Description": "Legal and operational classification of the trading venue",
            "AllowedValues": [
                "CFTC_DCM",
                "CFTC_SEF",
                "OffshoreExchange",
                "DecentralisedProtocol",
                "BilateralOTC",
                "Other",
            ],
            "Required": True,
        },
        "RegulatoryStatus": {
            "Description": "Regulatory classification of the contract in the applicable jurisdiction",
            "AllowedValues": [
                "Approved",
                "Conditional",
                "GamblingProhibited",
                "PublicPolicyProhibited",
                "NotApplicable",
                "Uncertain",
            ],
            "Required": True,
        },
    },
    "Derived": {
        "ClassificationType": "EventContract",
        "ShortName": "EventContract.Binary.PoliticalOutcome",
        "UnderlierName": "{ReferenceEntity} {EventDate}",
        "UnderlyingAssetType": "Event",
    },
}

EVENT_ECONOMIC_FUNCTION_TESTS = {
    "T026": {
        "quantifiable_exposure": {
            "status": "YES",
            "rationale": "A renewable-energy firm with German government subsidy exposure can identify revenue sensitivity to the election outcome.",
        },
        "viable_hedge_substitute": {
            "status": "PARTIAL",
            "rationale": "Power forwards, carbon allowances, FX/rates hedges, or structured derivatives can hedge some cash-flow channels, but not the binary political trigger directly.",
        },
        "price_discovery_beyond_public_data": {
            "status": "YES",
            "rationale": "Regulated prediction-market prices can provide a continuously updated probability signal beyond static polling averages.",
        },
        "engine_conclusion": "CONDITIONAL_EVENT_CONTRACT",
    },
    "T027": {
        "quantifiable_exposure": {
            "status": "YES",
            "rationale": "A fixed-income portfolio manager holding USD rates exposure can quantify CPI-driven mark-to-market losses.",
        },
        "viable_hedge_substitute": {
            "status": "YES_FUNCTIONAL_NOT_LEGAL",
            "rationale": "The payoff is economically analogous to CPI caps or inflation swaptions, but the offshore venue, missing LEIs, missing UTI, and USDC settlement block ordinary CFTC/EMIR reporting visibility.",
        },
        "price_discovery_beyond_public_data": {
            "status": "YES",
            "rationale": "Binary CPI prices can provide distributional probability information not directly observable from ordinary fixed-income instruments.",
        },
        "engine_conclusion": "NOT_REPORTABLE_EVENT_CONTRACT",
    },
    "T028": {
        "quantifiable_exposure": {
            "status": "YES",
            "rationale": "A fintech firm can quantify the compliance-cost timing effect of an AI Act deadline extension.",
        },
        "viable_hedge_substitute": {
            "status": "NO",
            "rationale": "No standard OTC instrument references the ESMA AI Act deadline as the underlying event.",
        },
        "price_discovery_beyond_public_data": {
            "status": "PARTIAL",
            "rationale": "The event may contain a useful regulatory probability signal, but thin volume and possible non-public information weaken informational reliability.",
        },
        "engine_conclusion": "CONDITIONAL_EVENT_CONTRACT",
    },
}


def load_trades(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("Input file must contain a JSON list of trade records.")
    return data


def load_codeset(product_definitions: Path, name: str) -> set[str]:
    path = product_definitions / "PROD" / "OTC-Products" / "codesets" / f"{name}.json"
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return set(payload.get("enum", []))


def load_codesets(product_definitions: Path) -> dict[str, set[str]]:
    rates = set()
    for name in [
        "FpmlRatesReferenceRate",
        "FpmlRatesReferenceAndInflationRate",
        "ISORatesReferenceRate",
        "ISORatesReferenceAndInflationRate",
    ]:
        rates.update(load_codeset(product_definitions, name))
    return {
        "currencies": load_codeset(product_definitions, "ISOCurrencyCode"),
        "rates": rates,
    }


def finding(
    rule_id: str,
    rule_name: str,
    regime: str,
    severity: str,
    message: str,
    field: str | None = None,
    status: str | None = None,
    finding_type: str = COMPLIANCE_FINDING,
) -> dict[str, str]:
    result = {
        "rule_id": rule_id,
        "rule_name": rule_name,
        "regime": regime,
        "severity": severity,
        "message": message,
        "finding_type": finding_type,
    }
    if field:
        result["field"] = field
    if status:
        result["status"] = status
    return result


def is_missing(value: Any) -> bool:
    return value is None or value == "" or value == "MISSING_LEI"


def parse_date(value: Any) -> bool:
    if not isinstance(value, str) or not DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def date_value(value: Any) -> datetime | None:
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


def timestamp_value(value: Any) -> datetime | None:
    if not isinstance(value, str) or not TIMESTAMP_UTC_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def timestamp_status(value: Any) -> tuple[str, str | None]:
    if not isinstance(value, str):
        return "FAILED", "timestamp is missing or not a string"
    if TIMESTAMP_UTC_RE.match(value):
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
            return "PASSED", None
        except ValueError:
            return "FAILED", "timestamp has UTC shape but is not a real datetime"
    if parse_date(value):
        return "PARTIAL", "timestamp is date-only; expected ISO 8601 UTC with T and Z"
    return "FAILED", "timestamp is not parseable as ISO 8601 UTC"


def classify_trade(trade: dict[str, Any]) -> str:
    asset_class = trade.get("asset_class")
    if asset_class == EVENT_ASSET_CLASS:
        return "NOVEL"
    if asset_class in CONVENTIONAL_ASSET_CLASSES:
        return "CONVENTIONAL"
    return "AMBIGUOUS"


def parse_trade(trade: dict[str, Any]) -> dict[str, Any]:
    flags: list[str] = []
    if is_missing(trade.get("trade_id")):
        flags.append("MISSING_TRADE_ID")
    for field_name in ["asset_class", "instrument_type", "use_case"]:
        if is_missing(trade.get(field_name)):
            flags.append(f"MISSING_{field_name.upper()}")

    ts_status, ts_message = timestamp_status(trade.get("timestamp"))
    if ts_status == "PARTIAL":
        flags.append("PARTIAL_TIMESTAMP")
    elif ts_status == "FAILED":
        flags.append("INVALID_TIMESTAMP")

    for field_name in ["trade_date", "effective_date", "maturity_date"]:
        value = trade.get(field_name)
        if not parse_date(value):
            flags.append(f"INVALID_{field_name.upper()}")

    declared = str(trade.get("declared_parse_status", trade.get("parse_status", ""))).upper()
    if "MISSING_TRADE_ID" in flags or ts_status == "FAILED" or declared == "FAILED":
        parse_status = "FAILED"
    elif flags or declared == "PARTIAL":
        parse_status = "PARTIAL"
    else:
        parse_status = "PASSED"

    return {
        "trade_id": trade.get("trade_id", "UNKNOWN"),
        "parse_status": parse_status,
        "engine_parse_status": parse_status,
        "declared_parse_status": declared or "UNSPECIFIED",
        "classification": classify_trade(trade),
        "data_quality_flags": flags,
        "timestamp_message": ts_message,
    }


def product_template_path(product_definitions: Path, asset: str, instrument: str, use_case: str) -> Path:
    filename = f"{asset}.{instrument}.{use_case}.UPI.V1.json"
    return product_definitions / "PROD" / "OTC-Products" / "UPI" / asset / filename


def map_product(trade: dict[str, Any]) -> tuple[str, str, str, list[str]]:
    key = (
        str(trade.get("asset_class", "")),
        str(trade.get("instrument_type", "")),
        str(trade.get("use_case", "")),
    )
    if key in PRODUCT_ALIASES:
        asset, instrument, use_case, note = PRODUCT_ALIASES[key]
        return asset, instrument, use_case, [note]
    asset = "Foreign_Exchange" if key[0] == "FX" else key[0]
    return asset, key[1], key[2], []


def collect_required(schema: dict[str, Any]) -> list[str]:
    required: list[str] = []

    def walk(node: Any, prefix: str) -> None:
        if not isinstance(node, dict):
            return
        for name in node.get("required", []):
            required.append(f"{prefix}.{name}" if prefix else name)
        props = node.get("properties", {})
        if isinstance(props, dict):
            for child_name, child in props.items():
                walk(child, f"{prefix}.{child_name}" if prefix else child_name)

    walk(schema, "")
    return sorted(set(required))


def validate_required_attribute_coverage(required_attributes: list[str], trade: dict[str, Any]) -> dict[str, Any]:
    relevant = [
        item
        for item in required_attributes
        if item.startswith("Attributes.") or item.startswith("Header.") or item == "Identifier.UPI"
    ]
    checked = []
    missing = []
    unmapped = []
    for dsb_attribute in relevant:
        trade_field = DSB_REQUIRED_FIELD_MAP.get(dsb_attribute)
        if not trade_field:
            unmapped.append(dsb_attribute)
            continue
        value = trade.get(trade_field)
        status = "PRESENT" if not is_missing(value) else "MISSING"
        checked.append(
            {
                "dsb_attribute": dsb_attribute,
                "trade_field": trade_field,
                "status": status,
            }
        )
        if status == "MISSING":
            missing.append(dsb_attribute)

    if missing:
        status = "PARTIAL"
    elif checked:
        status = "CHECKED"
    else:
        status = "UNMAPPED"

    return {
        "status": status,
        "checked_required_attributes": checked,
        "checked_required_count": len(checked),
        "missing_mapped_required_attributes": missing,
        "missing_mapped_required_count": len(missing),
        "unmapped_required_attributes_sample": unmapped[:12],
        "unmapped_required_count": len(unmapped),
        "note": (
            "这是基于当前样本字段对 ANNA-DSB required field name 的覆盖度检查。"
            "生产级系统应构造完整 DSB request payload，并校验全部 schema property 与 enum。"
        ),
    }


def normalized_rate_candidates(reference_rate: str) -> set[str]:
    candidates = {reference_rate}
    if reference_rate.endswith("-COMPOUND"):
        candidates.add(reference_rate[: -len("-COMPOUND")] + " Compound")
    candidates.add(reference_rate.replace("-OIS-COMPOUND", "-OIS Compound"))
    return candidates


def validate_currency(trade: dict[str, Any], currencies: set[str]) -> tuple[str, str]:
    value = trade.get("notional_currency")
    if is_missing(value):
        return "INVALID", "notional currency is missing"
    if not currencies:
        return "UNKNOWN", "currency codeset is unavailable"
    if value in currencies:
        return "VALID", f"{value} is present in ISOCurrencyCode"
    return "INVALID", f"{value} is not an ISO 4217 currency code in the DSB codeset"


def validate_reference_rate(trade: dict[str, Any], rates: set[str]) -> tuple[str, str | None]:
    reference_rate = trade.get("reference_rate")
    if is_missing(reference_rate):
        return "NOT_APPLICABLE", None
    if not rates:
        return "UNKNOWN", "rates reference-rate codeset is unavailable"
    candidates = normalized_rate_candidates(str(reference_rate))
    if reference_rate in rates:
        if "LIBOR" in str(reference_rate):
            return "WARNING", f"{reference_rate} remains in the codeset but is a legacy LIBOR rate; warn rather than hard-fail."
        return "VALID", f"{reference_rate} is present in the rates reference-rate codesets"
    matched_aliases = sorted(candidate for candidate in candidates if candidate in rates)
    if matched_aliases:
        return "WARNING", f"{reference_rate} is not exact, but normalized alias {matched_aliases[0]} exists in the codeset."
    return "INVALID", f"{reference_rate} is not present in the rates reference-rate codesets"


def lookup_upi(trade: dict[str, Any], product_definitions: Path, codesets: dict[str, set[str]]) -> dict[str, Any]:
    notes: list[str] = []
    if trade.get("asset_class") == EVENT_ASSET_CLASS:
        currency_status, currency_message = validate_currency(trade, codesets["currencies"])
        return {
            "template_found": False,
            "matched_template_path": None,
            "normalized_product": None,
            "required_attributes": [],
            "required_attribute_validation": {
                "status": "NO_PRODUCT_DEFINITION",
                "checked_required_attributes": [],
                "checked_required_count": 0,
                "missing_mapped_required_attributes": [],
                "missing_mapped_required_count": 0,
                "unmapped_required_attributes_sample": [],
                "unmapped_required_count": 0,
                "note": "No ANNA-DSB OTC UPI template exists for EventContract, so template-level attribute validation cannot be performed.",
            },
            "codeset_results": {
                "notional_currency": {"status": currency_status, "message": currency_message},
                "reference_rate": {"status": "NOT_APPLICABLE", "message": None},
            },
            "upi_status": "NO_PRODUCT_DEFINITION",
            "notes": ["EventContract has no ANNA-DSB UPI product definition in the OTC taxonomy."],
        }

    asset, instrument, use_case, mapping_notes = map_product(trade)
    notes.extend(mapping_notes)
    path = product_template_path(product_definitions, asset, instrument, use_case)
    template_found = path.exists()
    required_attributes: list[str] = []
    required_attribute_validation = {
        "status": "NO_TEMPLATE_MATCH",
        "checked_required_attributes": [],
        "checked_required_count": 0,
        "missing_mapped_required_attributes": [],
        "missing_mapped_required_count": 0,
        "unmapped_required_attributes_sample": [],
        "unmapped_required_count": 0,
        "note": "No matched ANNA-DSB UPI template was available for template-level required-attribute checks.",
    }
    if template_found:
        with path.open("r", encoding="utf-8") as fh:
            schema = json.load(fh)
        required_attributes = collect_required(schema)[:40]
        required_attribute_validation = validate_required_attribute_coverage(required_attributes, trade)

    currency_status, currency_message = validate_currency(trade, codesets["currencies"])
    rate_status, rate_message = validate_reference_rate(trade, codesets["rates"])

    if not template_found:
        status = "NO_TEMPLATE_MATCH"
        notes.append("No exact ANNA-DSB template file found for the normalized product path.")
    elif currency_status == "INVALID" or rate_status == "INVALID":
        status = "INVALID"
    elif currency_status == "UNKNOWN" or rate_status == "UNKNOWN":
        status = "WARNING"
    elif required_attribute_validation["missing_mapped_required_count"]:
        status = "WARNING"
        notes.append(
            "Matched DSB template, but some mapped required attributes are absent from the teaching-data record; treated as an attribute-coverage gap."
        )
    elif notes or rate_status == "WARNING":
        status = "WARNING"
    else:
        status = "VALID"

    return {
        "template_found": template_found,
        "matched_template_path": str(path.relative_to(product_definitions)) if template_found else str(path),
        "normalized_product": {
            "asset_class": asset,
            "instrument_type": instrument,
            "use_case": use_case,
        },
        "required_attributes": required_attributes,
        "required_attribute_validation": required_attribute_validation,
        "codeset_results": {
            "notional_currency": {"status": currency_status, "message": currency_message},
            "reference_rate": {"status": rate_status, "message": rate_message},
        },
        "upi_status": status,
        "notes": notes,
    }


def lei_to_number(value: str) -> str:
    parts: list[str] = []
    for char in value:
        if char.isdigit():
            parts.append(char)
        else:
            parts.append(str(ord(char) - 55))
    return "".join(parts)


def lei_check_digits_valid(lei: Any) -> bool:
    if not isinstance(lei, str):
        return False
    lei = lei.strip().upper()
    if not LEI_RE.match(lei):
        return False
    body = lei[:18]
    check_digits = lei[18:]
    computed = 98 - (int(lei_to_number(body + "00")) % 97)
    return f"{computed:02d}" == check_digits and int(lei_to_number(lei)) % 97 == 1


def validate_lei_field(trade: dict[str, Any], field_name: str) -> list[dict[str, str]]:
    value = trade.get(field_name)
    label = field_name.replace("_", " ")
    if is_missing(value):
        return [
            finding(
                "LEI_MISSING",
                "LEI presence",
                "GLOBAL",
                "NONCOMPLIANT",
                f"{label} is missing or uses a placeholder.",
                field_name,
            )
        ]
    if not isinstance(value, str) or not LEI_RE.match(value):
        return [
            finding(
                "LEI_FORMAT",
                "LEI format",
                "GLOBAL",
                "NONCOMPLIANT",
                f"{label} must be a 20-character uppercase alphanumeric LEI.",
                field_name,
            )
        ]
    if not lei_check_digits_valid(value):
        return [
            finding(
                "LEI_CHECK_DIGIT",
                "LEI ISO 7064 check digit",
                "GLOBAL",
                "NONCOMPLIANT",
                f"{label} fails ISO 7064 MOD 97-10 check-digit validation.",
                field_name,
            )
        ]
    return []


def validate_uti(trade: dict[str, Any], duplicate_utis: set[str]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    uti = trade.get("uti")
    reporting_lei = trade.get("reporting_counterparty_lei")
    if is_missing(uti):
        return [
            finding(
                "UTI_MISSING",
                "UTI presence",
                "GLOBAL",
                "NONCOMPLIANT",
                "UTI is missing.",
                "uti",
            )
        ]
    uti = str(uti)
    if len(uti) > 52:
        results.append(
            finding("UTI_LENGTH", "UTI length", "GLOBAL", "NONCOMPLIANT", "UTI exceeds the ISO 23897 52-character maximum.", "uti")
        )
    if len(uti) < 21:
        results.append(
            finding("UTI_FORMAT", "UTI format", "GLOBAL", "NONCOMPLIANT", "UTI must contain a 20-character LEI namespace plus a suffix.", "uti")
        )
        return results
    namespace, suffix = uti[:20], uti[20:]
    if namespace != reporting_lei:
        results.append(
            finding(
                "UTI_NAMESPACE",
                "UTI namespace",
                "GLOBAL",
                "NONCOMPLIANT",
                "First 20 characters of UTI do not equal reporting_counterparty_lei.",
                "uti",
            )
        )
    if not LEI_RE.match(namespace):
        results.append(
            finding(
                "UTI_NAMESPACE_FORMAT",
                "UTI namespace format",
                "GLOBAL",
                "NONCOMPLIANT",
                "UTI namespace is not a 20-character uppercase alphanumeric LEI namespace.",
                "uti",
            )
        )
    if not UTI_SUFFIX_RE.match(suffix):
        results.append(
            finding(
                "UTI_SUFFIX",
                "UTI suffix character set",
                "GLOBAL",
                "NONCOMPLIANT",
                "UTI suffix must contain only uppercase letters, digits, and hyphens.",
                "uti",
            )
        )
    if uti in duplicate_utis:
        results.append(
            finding("UTI_DUPLICATE", "Duplicate UTI", "GLOBAL", "NONCOMPLIANT", "UTI is duplicated elsewhere in the portfolio.", "uti")
        )
    return results


def validate_timestamp_and_dates(trade: dict[str, Any]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    status, message = timestamp_status(trade.get("timestamp"))
    if status == "PARTIAL":
        results.append(
            finding("TIMESTAMP_PARTIAL", "Timestamp UTC format", "GLOBAL", "WARNING", message or "Timestamp is partial.", "timestamp")
        )
    elif status == "FAILED":
        results.append(
            finding("TIMESTAMP_INVALID", "Timestamp UTC format", "GLOBAL", "NONCOMPLIANT", message or "Timestamp is invalid.", "timestamp")
        )
    for field_name in ["trade_date", "effective_date", "maturity_date"]:
        if not parse_date(trade.get(field_name)):
            results.append(
                finding(
                    "DATE_INVALID",
                    "Calendar date validity",
                    "GLOBAL",
                    "WARNING",
                    f"{field_name} is missing or not a real YYYY-MM-DD calendar date.",
                    field_name,
                )
            )
    return results


def business_validation_findings(trade: dict[str, Any]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    trade_date = date_value(trade.get("trade_date"))
    effective_date = date_value(trade.get("effective_date"))
    maturity_date = date_value(trade.get("maturity_date"))

    if trade_date and effective_date and trade_date > effective_date:
        results.append(
            finding(
                "DATE_ORDER",
                "Business date order",
                "GLOBAL",
                "NONCOMPLIANT",
                "trade_date must be on or before effective_date.",
                "effective_date",
            )
        )
    if effective_date and maturity_date and effective_date > maturity_date:
        results.append(
            finding(
                "DATE_ORDER",
                "Business date order",
                "GLOBAL",
                "NONCOMPLIANT",
                "effective_date must be on or before maturity_date.",
                "maturity_date",
            )
        )

    timestamp = timestamp_value(trade.get("timestamp"))
    if timestamp and trade_date and timestamp.date() < trade_date.date():
        results.append(
            finding(
                "TIMESTAMP_BEFORE_TRADE_DATE",
                "Timestamp business consistency",
                "GLOBAL",
                "NONCOMPLIANT",
                "timestamp must not be earlier than trade_date.",
                "timestamp",
            )
        )

    notional = trade.get("notional_amount")
    if not isinstance(notional, (int, float)) or isinstance(notional, bool) or notional <= 0:
        results.append(
            finding(
                "NOTIONAL_AMOUNT",
                "Positive notional amount",
                "GLOBAL",
                "NONCOMPLIANT",
                "notional_amount must be a positive number.",
                "notional_amount",
            )
        )

    for field_name in ["initial_margin_posted", "variation_margin_posted", "collateral_margin_posted"]:
        value = trade.get(field_name)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0):
            results.append(
                finding(
                    "NEGATIVE_MARGIN",
                    "Non-negative margin amount",
                    "GLOBAL",
                    "NONCOMPLIANT",
                    f"{field_name} must be zero or a positive number when provided.",
                    field_name,
                )
            )

    if not isinstance(trade.get("cleared"), bool):
        results.append(
            finding(
                "CLEARED_TYPE",
                "Cleared flag type",
                "GLOBAL",
                "NONCOMPLIANT",
                "cleared must be a boolean value.",
                "cleared",
            )
        )

    action_type = trade.get("action_type")
    if not is_missing(action_type) and action_type not in ALLOWED_ACTION_TYPES:
        results.append(
            finding(
                "ACTION_TYPE_ENUM",
                "Action type enumeration",
                "GLOBAL",
                "NONCOMPLIANT",
                f"action_type {action_type} is not in the supported lifecycle-event set.",
                "action_type",
            )
        )
    return results


def required_field_findings(trade: dict[str, Any], regime: str, fields: Iterable[str]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for field_name in fields:
        value = trade.get(field_name)
        if is_missing(value):
            results.append(
                finding(
                    f"{regime}_REQUIRED_FIELD",
                    f"{regime} required field",
                    regime,
                    "NONCOMPLIANT",
                    f"{field_name} is required under {regime} reporting checks.",
                    field_name,
                )
            )
    return results


def placeholder_upi_findings(trade: dict[str, Any], regime: str) -> list[dict[str, str]]:
    upi = trade.get("upi")
    if isinstance(upi, str) and upi.startswith("PLACEHOLDER_"):
        return [
            finding(
                "UPI_PLACEHOLDER",
                "UPI placeholder",
                regime,
                "INFO",
                "UPI field is populated but still uses a teaching-data placeholder; production reporting would need the issued UPI.",
                "upi",
            )
        ]
    return []


def margin_findings(trade: dict[str, Any], regime: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for field_name in ["initial_margin_posted", "variation_margin_posted", "collateral_margin_posted"]:
        if trade.get(field_name) is None:
            results.append(
                finding(
                    f"{regime}_NULL_MARGIN",
                    f"{regime} margin value",
                    regime,
                    "NONCOMPLIANT",
                    f"{field_name} is null. Under {regime}, zero must be reported as 0; null is a compliance failure.",
                    field_name,
                )
            )
    return results


def cftc_event_contract_findings(trade: dict[str, Any]) -> list[dict[str, str]]:
    platform_type = str(trade.get("platform_type", "")).upper()
    case_status = trade.get("case_file_cftc_status", trade.get("cftc_status", "UNKNOWN"))
    if platform_type == "CFTC_DCM" or case_status == "CONDITIONAL":
        return [
            finding(
                "CFTC_EVENT_CONDITIONAL",
                "CFTC event-contract treatment",
                "CFTC",
                "WARNING",
                f"{trade.get('trade_id')} is a Kalshi-style event contract on a CFTC DCM. Treat as CONDITIONAL rather than a conventional OTC swap.",
                "asset_class",
                "CONDITIONAL",
                SCOPE_FINDING,
            )
        ]
    if "OFFSHORE" in platform_type or "DECENTR" in platform_type or case_status == "NOT_APPLICABLE":
        return [
            finding(
                "CFTC_EVENT_NOT_APPLICABLE",
                "CFTC event-contract treatment",
                "CFTC",
                "INFO",
                f"{trade.get('trade_id')} is not reportable through the CFTC OTC swap reporting path based on the provided platform facts.",
                "asset_class",
                "NOT_APPLICABLE",
                SCOPE_FINDING,
            )
        ]
    return [
        finding(
            "CFTC_EVENT_AMBIGUOUS",
            "CFTC event-contract treatment",
            "CFTC",
            "WARNING",
            "Event-contract regulatory treatment is ambiguous and needs legal classification.",
            "asset_class",
            "REGULATORY_AMBIGUOUS",
            SCOPE_FINDING,
        )
    ]


def mas_event_contract_findings(trade: dict[str, Any]) -> list[dict[str, str]]:
    if trade.get("booked_in_sg") or trade.get("traded_in_sg"):
        severity = "WARNING"
        message = "EventContract has a Singapore nexus but no OTC UPI taxonomy entry; classify before applying MAS field rules."
        status = "REGULATORY_AMBIGUOUS"
    else:
        severity = "INFO"
        message = "No Singapore booking/trading nexus is provided, so MAS reporting is treated as not applicable for this event contract."
        status = "NOT_APPLICABLE"
    return [
        finding(
            "MAS_EVENT_SCOPE",
            "MAS event-contract scope",
            "MAS",
            severity,
            message,
            "asset_class",
            status,
            SCOPE_FINDING,
        )
    ]


def emir_event_contract_findings(trade: dict[str, Any]) -> list[dict[str, str]]:
    case_status = trade.get("case_file_emir_status", trade.get("emir_status", "UNKNOWN"))
    if case_status == "NOT_APPLICABLE":
        severity = "INFO"
        message = "Case-file facts mark this EventContract as outside the selected EMIR OTC reporting path."
        status = "NOT_APPLICABLE"
    else:
        severity = "WARNING"
        message = "EventContract has no OTC UPI taxonomy entry; classify before applying ordinary EMIR field rules."
        status = "REGULATORY_AMBIGUOUS"
    return [
        finding(
            "EMIR_EVENT_SCOPE",
            "EMIR event-contract scope",
            "EMIR",
            severity,
            message,
            "asset_class",
            status,
            SCOPE_FINDING,
        )
    ]


def regime_findings(trade: dict[str, Any], regimes: list[str]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    asset_class = trade.get("asset_class")
    for regime in regimes:
        regime = regime.upper()
        if regime == "CFTC":
            if asset_class == EVENT_ASSET_CLASS:
                results.extend(cftc_event_contract_findings(trade))
                continue
            required = REGIME_RULES["CFTC"]["required_fields"]
            results.extend(required_field_findings(trade, "CFTC", required))
        elif regime == "MAS":
            if asset_class == EVENT_ASSET_CLASS:
                results.extend(mas_event_contract_findings(trade))
                continue
            required = REGIME_RULES["MAS"]["required_fields"]
            results.extend(required_field_findings(trade, "MAS", required))
            results.extend(margin_findings(trade, "MAS"))
            if trade.get("booked_in_sg") or trade.get("traded_in_sg"):
                results.append(
                    finding(
                        "MAS_SG_NEXUS",
                        "MAS reporting scope",
                        "MAS",
                        "INFO",
                        "交易存在 Singapore booking 或 trading nexus；MAS reporting scope 需要重点关注。",
                        "booked_in_sg",
                        "IN_SCOPE",
                        SCOPE_FINDING,
                    )
                )
            else:
                results.append(
                    finding(
                        "MAS_SG_NEXUS",
                        "MAS reporting scope",
                        "MAS",
                        "INFO",
                        "No Singapore booking/trading nexus is marked, but technical required-field checks were still run for portfolio comparability.",
                        "booked_in_sg",
                        "OUT_OF_SCOPE_INDICATIVE",
                        SCOPE_FINDING,
                    )
                )
        elif regime == "EMIR":
            if asset_class == EVENT_ASSET_CLASS:
                results.extend(emir_event_contract_findings(trade))
                continue
            required = REGIME_RULES["EMIR"]["required_fields"]
            results.extend(required_field_findings(trade, "EMIR", required))
            results.extend(margin_findings(trade, "EMIR"))
        else:
            results.append(
                finding(
                    "REGIME_UNSUPPORTED",
                    "Unsupported regime",
                    regime,
                    "WARNING",
                    f"{regime} was requested but this prototype implements CFTC, MAS, and EMIR.",
                )
            )
    return results


def codeset_findings(trade: dict[str, Any], upi: dict[str, Any]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    currency = upi["codeset_results"]["notional_currency"]
    if currency["status"] == "INVALID":
        severity = "WARNING" if trade.get("asset_class") == EVENT_ASSET_CLASS else "NONCOMPLIANT"
        results.append(
            finding(
                "INVALID_CURRENCY",
                "ISO 4217 currency validation",
                "GLOBAL",
                severity,
                currency["message"],
                "notional_currency",
            )
        )
    rate = upi["codeset_results"]["reference_rate"]
    if rate["status"] == "INVALID":
        results.append(
            finding(
                "INVALID_REFERENCE_RATE",
                "Rates reference-rate codeset validation",
                "GLOBAL",
                "NONCOMPLIANT",
                rate["message"],
                "reference_rate",
            )
        )
    elif rate["status"] == "WARNING":
        rule_id = "LIBOR_WARNING" if "LIBOR" in str(trade.get("reference_rate")) else "REFERENCE_RATE_ALIAS"
        results.append(
            finding(
                rule_id,
                "Rates reference-rate codeset validation",
                "GLOBAL",
                "WARNING",
                rate["message"],
                "reference_rate",
            )
        )
    return results


def upi_findings(trade: dict[str, Any], upi: dict[str, Any]) -> list[dict[str, str]]:
    status = upi["upi_status"]
    if status == "NO_PRODUCT_DEFINITION":
        return [
            finding(
                "NO_PRODUCT_DEFINITION",
                "ANNA-DSB UPI taxonomy coverage",
                "GLOBAL",
                "WARNING",
                "No ANNA-DSB OTC product definition exists for EventContract; this is a taxonomy gap, not a parser crash.",
                "asset_class",
                "REGULATORY_AMBIGUOUS",
            )
        ]
    if status == "NO_TEMPLATE_MATCH":
        return [
            finding(
                "NO_TEMPLATE_MATCH",
                "ANNA-DSB UPI template lookup",
                "GLOBAL",
                "WARNING",
                "No exact UPI template matched after product normalization.",
                "use_case",
            )
        ]
    if status == "WARNING":
        notes = upi.get("notes", [])
        message = "; ".join(notes) or "Template matched with caveats."
        warning_fragments = [
            "representative",
            "closest",
            "source data does not specify",
            "required attributes are absent",
            "attribute-coverage gap",
        ]
        severity = "WARNING" if any(fragment in message.lower() for fragment in warning_fragments) else "INFO"
        return [
            finding(
                "UPI_TEMPLATE_MAPPING",
                "ANNA-DSB UPI template lookup",
                "GLOBAL",
                severity,
                message,
                "use_case",
            )
        ]
    return []


def overall_status(findings: list[dict[str, str]], classification: str, conclusion: str) -> str:
    if conclusion == "NOT_REPORTABLE_EVENT_CONTRACT":
        return "NOT_REPORTABLE"
    if conclusion in {"CONDITIONAL_EVENT_CONTRACT", "REGULATORY_AMBIGUOUS_EVENT_CONTRACT"}:
        return "REGULATORY_AMBIGUOUS"
    max_rank = max((SEVERITY_RANK.get(item["severity"], 0) for item in findings), default=0)
    if max_rank == 2:
        return "NONCOMPLIANT"
    if classification == "NOVEL":
        return "REGULATORY_AMBIGUOUS"
    if max_rank == 1:
        return "WARNING"
    return "COMPLIANT"


def data_quality_status(compliance_findings: list[dict[str, str]]) -> str:
    max_rank = max((SEVERITY_RANK.get(item["severity"], 0) for item in compliance_findings), default=0)
    if max_rank == 2:
        return "NONCOMPLIANT"
    if max_rank == 1:
        return "WARNING"
    return "PASS"


def reporting_scope_status(trade: dict[str, Any], conclusion: str) -> str:
    if trade.get("asset_class") != EVENT_ASSET_CLASS:
        return "IN_SCOPE"
    if conclusion == "NOT_REPORTABLE_EVENT_CONTRACT":
        return "OUT_OF_SCOPE"
    if conclusion == "CONDITIONAL_EVENT_CONTRACT":
        return "CONDITIONAL"
    return "AMBIGUOUS"


def event_economic_function_test(trade: dict[str, Any]) -> dict[str, Any] | None:
    if trade.get("asset_class") != EVENT_ASSET_CLASS:
        return None
    return EVENT_ECONOMIC_FUNCTION_TESTS.get(str(trade.get("trade_id")))


def event_supervisory_flags(
    trade: dict[str, Any],
    upi: dict[str, Any],
    findings: list[dict[str, str]],
) -> dict[str, Any] | None:
    if trade.get("asset_class") != EVENT_ASSET_CLASS:
        return None

    rule_ids = {item["rule_id"] for item in findings}
    platform_type = str(trade.get("platform_type", "")).upper()
    notional = trade.get("notional_amount")
    non_iso_settlement = "INVALID_CURRENCY" in rule_ids
    missing_identifier_visibility = bool({"LEI_MISSING", "UTI_MISSING"} & rule_ids)
    no_upi_taxonomy = upi.get("upi_status") == "NO_PRODUCT_DEFINITION"
    regulated_cftc_venue = platform_type == "CFTC_DCM"
    offshore_or_decentralised = "OFFSHORE" in platform_type or "DECENTR" in platform_type

    recommended_action = "NO_EVENT_SPECIFIC_CFTC_ACTION"
    if regulated_cftc_venue and no_upi_taxonomy:
        recommended_action = "PART45_DCM_EVENT_REPORTING_CANDIDATE"
    elif offshore_or_decentralised and (non_iso_settlement or missing_identifier_visibility):
        if isinstance(notional, (int, float)) and not isinstance(notional, bool) and notional >= CFTC_EC1_NOTIFICATION_THRESHOLD_USD:
            recommended_action = "EC1_NOTIFICATION_CANDIDATE"
        else:
            recommended_action = "EC1_REVIEW_BELOW_PROPOSED_THRESHOLD"

    return {
        "regulated_cftc_venue": regulated_cftc_venue,
        "offshore_or_decentralised": offshore_or_decentralised,
        "no_upi_taxonomy": no_upi_taxonomy,
        "non_iso_settlement_currency": non_iso_settlement,
        "missing_identifier_visibility": missing_identifier_visibility,
        "ec1_threshold_usd": CFTC_EC1_NOTIFICATION_THRESHOLD_USD,
        "ec1_threshold_status": (
            "MET_OR_EXCEEDED"
            if isinstance(notional, (int, float)) and not isinstance(notional, bool) and notional >= CFTC_EC1_NOTIFICATION_THRESHOLD_USD
            else "BELOW_THRESHOLD"
        ),
        "recommended_cftc_action": recommended_action,
    }


def event_source_facts(trade: dict[str, Any]) -> dict[str, Any] | None:
    if trade.get("asset_class") != EVENT_ASSET_CLASS:
        return None
    return {
        "platform": trade.get("platform"),
        "platform_type": trade.get("platform_type"),
        "event_description": trade.get("event_description"),
        "hedger_type": trade.get("hedger_type"),
        "notional_currency": trade.get("notional_currency"),
        "booked_in_sg": trade.get("booked_in_sg"),
        "traded_in_sg": trade.get("traded_in_sg"),
        "case_file_cftc_status": trade.get("case_file_cftc_status", trade.get("cftc_status")),
        "case_file_emir_status": trade.get("case_file_emir_status", trade.get("emir_status")),
        "case_file_regulatory_note": trade.get("case_file_regulatory_note", trade.get("finding")),
    }


def classification_conclusion(trade: dict[str, Any], parse_result: dict[str, Any], upi: dict[str, Any]) -> str:
    if trade.get("asset_class") != EVENT_ASSET_CLASS:
        return parse_result["classification"]
    platform_type = str(trade.get("platform_type", "")).upper()
    if platform_type == "CFTC_DCM":
        return "CONDITIONAL_EVENT_CONTRACT"
    if "OFFSHORE" in platform_type or "DECENTR" in platform_type:
        return "NOT_REPORTABLE_EVENT_CONTRACT"
    case_cftc_status = trade.get("case_file_cftc_status", trade.get("cftc_status"))
    if case_cftc_status == "CONDITIONAL":
        return "CONDITIONAL_EVENT_CONTRACT"
    if case_cftc_status == "NOT_APPLICABLE":
        return "NOT_REPORTABLE_EVENT_CONTRACT"
    if upi["upi_status"] == "NO_PRODUCT_DEFINITION":
        return "REGULATORY_AMBIGUOUS_EVENT_CONTRACT"
    return "NOVEL"


def event_contract_analysis(analyzed: list[dict[str, Any]]) -> dict[str, Any]:
    event_rows = [row for row in analyzed if row["asset_class"] == EVENT_ASSET_CLASS]
    return {
        "schema_proposal": EVENT_CONTRACT_UPI_SCHEMA,
        "economic_function_tests": {
            row["trade_id"]: row["economic_function_test"]
            for row in event_rows
            if row.get("economic_function_test")
        },
        "supervisory_flags": {
            row["trade_id"]: row["supervisory_flags"]
            for row in event_rows
            if row.get("supervisory_flags")
        },
        "regulatory_references": [
            {
                "name": "CFTC Prediction Markets ANPR",
                "citation": "91 FR 12516, RIN 3038-AF65, March 16, 2026",
                "relevance": "Confirms the CFTC is seeking comment on event-contract derivatives traded on prediction markets and can use comments to inform future rulemaking.",
            },
            {
                "name": "Diercks, Katz and Wright (2026)",
                "citation": "Kalshi and the Rise of Macro Markets, NBER Working Paper 34702 / FEDS 2026-010",
                "relevance": "Supports the price-discovery premise for regulated macro prediction markets.",
            },
            {
                "name": "Brandes (2026)",
                "citation": "The Unhedgeable State: Why Europe's Risk Management Architecture Has a Political Risk Gap",
                "relevance": "Supports functional classification based on operator neutrality, financial exposure, and incremental price discovery.",
            },
        ],
        "cftc_recommendations": [
            {
                "recommendation_id": "PART45_DCM_EVENT_REPORTING",
                "title": "Extend SDR-style reporting to CFTC-licensed DCM event contracts above a materiality threshold.",
                "engine_impact": "T026 and T028 would move from CFTC_EVENT_CONDITIONAL to a directly reportable event-contract scope if the rule supplied UPI, LEI, UTI, event, and venue fields.",
            },
            {
                "recommendation_id": "EC1_NON_ISO_SETTLEMENT_REVIEW",
                "title": "Create a novel-instrument notification or review trigger for offshore or stablecoin-settled event contracts.",
                "engine_impact": "T027 combines non-ISO USDC settlement, missing LEIs, missing UTI, no UPI taxonomy, and offshore/decentralised venue facts. Its notional is below the illustrative USD 100,000 filing threshold, so the engine treats it as a review flag rather than an automatic filing obligation.",
            },
        ],
    }


def analyze_trades(
    trades: list[dict[str, Any]],
    product_definitions: Path,
    regimes: list[str],
) -> dict[str, Any]:
    codesets = load_codesets(product_definitions)
    uti_counts = Counter(str(t.get("uti")) for t in trades if not is_missing(t.get("uti")))
    duplicate_utis = {uti for uti, count in uti_counts.items() if count > 1}

    analyzed = []
    for trade in trades:
        parse_result = parse_trade(trade)
        upi_result = lookup_upi(trade, product_definitions, codesets)
        findings: list[dict[str, str]] = []
        findings.extend(upi_findings(trade, upi_result))
        findings.extend(placeholder_upi_findings(trade, "GLOBAL"))
        findings.extend(codeset_findings(trade, upi_result))
        findings.extend(validate_lei_field(trade, "reporting_counterparty_lei"))
        findings.extend(validate_lei_field(trade, "other_counterparty_lei"))
        findings.extend(validate_uti(trade, duplicate_utis))
        findings.extend(validate_timestamp_and_dates(trade))
        findings.extend(business_validation_findings(trade))
        findings.extend(regime_findings(trade, regimes))

        conclusion = classification_conclusion(trade, parse_result, upi_result)
        scope_assessments = [item for item in findings if item.get("finding_type") == SCOPE_FINDING]
        compliance_findings = [item for item in findings if item.get("finding_type") != SCOPE_FINDING]
        dq_status = data_quality_status(compliance_findings)
        scope_status = reporting_scope_status(trade, conclusion)
        economic_test = event_economic_function_test(trade)
        supervisory_flags = event_supervisory_flags(trade, upi_result, findings)
        analyzed.append(
            {
                "trade_id": parse_result["trade_id"],
                "asset_class": trade.get("asset_class"),
                "instrument_type": trade.get("instrument_type"),
                "use_case": trade.get("use_case"),
                "source_facts": event_source_facts(trade),
                "parse": parse_result,
                "upi": upi_result,
                "economic_function_test": economic_test,
                "supervisory_flags": supervisory_flags,
                "classification_conclusion": conclusion,
                "regulatory_conclusion": conclusion,
                "data_quality_status": dq_status,
                "reporting_scope_status": scope_status,
                "overall_status": overall_status(findings, parse_result["classification"], conclusion),
                "compliance_findings": compliance_findings,
                "scope_assessments": scope_assessments,
                "findings": findings,
            }
        )

    summary = summarize(analyzed)
    return {
        "metadata": {
            "engine_name": "衍生品交易报告合规审查工作台规则引擎",
            "regimes": regimes,
            "trade_count": len(trades),
            "product_definitions_path": str(product_definitions),
        },
        "summary": summary,
        "event_contract_analysis": event_contract_analysis(analyzed),
        "trades": analyzed,
    }


def summarize(analyzed: list[dict[str, Any]]) -> dict[str, Any]:
    severity_counts: Counter[str] = Counter()
    all_rule_counts: Counter[str] = Counter()
    compliance_rule_counts: Counter[str] = Counter()
    substantive_rule_counts: Counter[str] = Counter()
    scope_rule_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    data_quality_counts: Counter[str] = Counter()
    reporting_scope_counts: Counter[str] = Counter()
    asset_status: dict[str, Counter[str]] = defaultdict(Counter)
    classification_counts: Counter[str] = Counter()
    regulatory_conclusion_counts: Counter[str] = Counter()
    parse_counts: Counter[str] = Counter()

    for row in analyzed:
        status_counts[row["overall_status"]] += 1
        data_quality_counts[row["data_quality_status"]] += 1
        reporting_scope_counts[row["reporting_scope_status"]] += 1
        asset_status[str(row["asset_class"])][row["overall_status"]] += 1
        classification_counts[row["classification_conclusion"]] += 1
        regulatory_conclusion_counts[row["regulatory_conclusion"]] += 1
        parse_counts[row["parse"]["parse_status"]] += 1
        for item in row["findings"]:
            severity_counts[item["severity"]] += 1
            all_rule_counts[item["rule_id"]] += 1
            if item.get("finding_type") == SCOPE_FINDING:
                scope_rule_counts[item["rule_id"]] += 1
            else:
                compliance_rule_counts[item["rule_id"]] += 1
                if item.get("severity") != "INFO" and item["rule_id"] not in {
                    "UPI_PLACEHOLDER",
                    "UPI_TEMPLATE_MAPPING",
                    "REFERENCE_RATE_ALIAS",
                }:
                    substantive_rule_counts[item["rule_id"]] += 1

    return {
        "overall_status_counts": dict(status_counts),
        "data_quality_status_counts": dict(data_quality_counts),
        "reporting_scope_status_counts": dict(reporting_scope_counts),
        "severity_counts": dict(severity_counts),
        "all_rule_counts": dict(all_rule_counts.most_common()),
        "top_rule_counts": dict(compliance_rule_counts.most_common()),
        "top_compliance_rule_counts": dict(compliance_rule_counts.most_common()),
        "top_substantive_rule_counts": dict(substantive_rule_counts.most_common()),
        "scope_rule_counts": dict(scope_rule_counts.most_common()),
        "asset_class_status_counts": {asset: dict(counts) for asset, counts in sorted(asset_status.items())},
        "classification_counts": dict(classification_counts),
        "regulatory_conclusion_counts": dict(regulatory_conclusion_counts),
        "parse_status_counts": dict(parse_counts),
    }


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def ensure_plotly_bundle(dashboard_dir: Path) -> None:
    assets_dir = dashboard_dir / "assets"
    ensure_dir(assets_dir)
    target = assets_dir / "plotly.min.js"
    if target.exists():
        return
    try:
        import plotly  # type: ignore

        source = Path(plotly.__file__).resolve().parent / "package_data" / "plotly.min.js"
        if source.exists():
            shutil.copyfile(source, target)
            return
        from plotly.offline import get_plotlyjs  # type: ignore

        target.write_text(get_plotlyjs(), encoding="utf-8")
    except Exception:
        target.write_text(
            "window.Plotly = window.Plotly || null;\n"
            "console.warn('Local Plotly bundle was not available when this dashboard was generated.');\n",
            encoding="utf-8",
        )


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)


def write_findings_csv(path: Path, results: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    fields = [
        "trade_id",
        "asset_class",
        "overall_status",
        "data_quality_status",
        "reporting_scope_status",
        "regulatory_conclusion",
        "finding_type",
        "rule_id",
        "rule_name",
        "regime",
        "severity",
        "field",
        "status",
        "message",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for trade in results["trades"]:
            for item in trade["findings"]:
                writer.writerow(
                    {
                        "trade_id": trade["trade_id"],
                        "asset_class": trade["asset_class"],
                        "overall_status": trade["overall_status"],
                        "data_quality_status": trade["data_quality_status"],
                        "reporting_scope_status": trade["reporting_scope_status"],
                        "regulatory_conclusion": trade["regulatory_conclusion"],
                        "finding_type": item.get("finding_type", ""),
                        "rule_id": item.get("rule_id", ""),
                        "rule_name": item.get("rule_name", ""),
                        "regime": item.get("regime", ""),
                        "severity": item.get("severity", ""),
                        "field": item.get("field", ""),
                        "status": item.get("status", ""),
                        "message": item.get("message", ""),
                    }
                )


def severity_for_rule(trade: dict[str, Any], rule_fragment: str) -> str:
    ranks = [SEVERITY_RANK[item["severity"]] for item in findings_for_rule_fragment(trade, rule_fragment)]
    if not ranks:
        return "PASS"
    rank = max(ranks)
    if rank == 2:
        return "FAIL"
    if rank == 1:
        return "WARN"
    return "INFO"


def findings_for_rule_fragment(trade: dict[str, Any], rule_fragment: str) -> list[dict[str, Any]]:
    return [
        item
        for item in trade.get("findings", [])
        if rule_fragment in item["rule_id"] or rule_fragment in item["rule_name"].upper()
    ]


def heatmap_hover_text(trade: dict[str, Any], family: str, status: str, lang: str = "zh") -> str:
    if family == "PARSE":
        key_finding = trade["parse"].get("engine_parse_status", trade["parse"].get("parse_status", status))
    else:
        findings = findings_for_rule_fragment(trade, family)
        if findings:
            counts = Counter(item["rule_id"] for item in findings)
            key_finding = ", ".join(
                f"{rule_id} x{count}" if count > 1 else rule_id
                for rule_id, count in counts.most_common(3)
            )
        else:
            key_finding = "No material issue" if lang == "en" else "无明显问题"
    labels = (
        ("Trade", "Control family", "Status", "Key finding")
        if lang == "en"
        else ("交易", "校验家族", "状态", "关键发现")
    )
    return (
        f"{labels[0]}: {trade['trade_id']}<br>"
        f"{labels[1]}: {family}<br>"
        f"{labels[2]}: {status}<br>"
        f"{labels[3]}: {key_finding}"
    )


def dashboard_cell(status: str) -> str:
    label = html.escape(status)
    return f'<td class="{label.lower()}">{label}</td>'


def i18n_attrs(zh: str, en: str) -> str:
    return f'data-i18n-zh="{html.escape(zh, quote=True)}" data-i18n-en="{html.escape(en, quote=True)}"'


def i18n_element(tag: str, zh: str, en: str, attrs: str = "") -> str:
    attr_text = f" {attrs.strip()}" if attrs else ""
    return f"<{tag}{attr_text} {i18n_attrs(zh, en)}>{html.escape(zh)}</{tag}>"


def i18n_span(zh: str, en: str, attrs: str = "") -> str:
    return i18n_element("span", zh, en, attrs)


def i18n_th(zh: str, en: str) -> str:
    return i18n_element("th", zh, en)


def dashboard_status_class(value: Any) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", str(value).lower().replace("_", "-")).strip("-")


def dashboard_badge(value: Any) -> str:
    label = html.escape(str(value).replace("_", " "))
    return f'<span class="badge {dashboard_status_class(value)}">{label}</span>'


def short_dashboard_note(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    shortened = text[: limit - 3].rsplit(" ", 1)[0]
    return f"{shortened}..."


def event_regulatory_note(trade: dict[str, Any]) -> str:
    notes = [
        str(item.get("message", ""))
        for item in trade.get("findings", [])
        if "EVENT" in str(item.get("rule_id", "")) or item.get("rule_id") == "NO_PRODUCT_DEFINITION"
    ]
    if notes:
        return short_dashboard_note("; ".join(notes))
    source_facts = trade.get("source_facts") or {}
    return short_dashboard_note(source_facts.get("case_file_regulatory_note", "未记录事件合约专项监管说明。"))


def dashboard_css() -> str:
    return """
    :root {
      --ink: #17202a;
      --muted: #5b677a;
      --panel: #ffffff;
      --line: #d9e0ea;
      --page: #f5f7fa;
      --nav: #102a43;
      --blue: #2458a6;
      --green: #2f855a;
      --yellow: #946200;
      --red: #b42318;
      --slate: #475467;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body { margin: 0; font-family: Arial, sans-serif; color: var(--ink); background: var(--page); }
    header { padding: 30px 40px 26px; background: linear-gradient(135deg, #102a43 0%, #1f4e79 100%); color: white; }
    header h1 { margin: 4px 0 8px; font-size: 30px; letter-spacing: 0; }
    header p { margin: 0; max-width: 980px; line-height: 1.5; color: #e6edf5; }
    .header-top { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 4px; }
    .eyebrow { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: #bfd7f2; font-weight: 700; }
    .language-toggle { display: inline-flex; flex: 0 0 auto; gap: 2px; padding: 3px; border: 1px solid rgba(255,255,255,.38); border-radius: 7px; background: rgba(255,255,255,.12); }
    .lang-button { min-width: 44px; min-height: 28px; border: 0; border-radius: 5px; padding: 5px 9px; color: #e6edf5; background: transparent; font-size: 12px; font-weight: 800; cursor: pointer; }
    .lang-button.is-active { color: #102a43; background: #ffffff; }
    .lang-button:focus-visible { outline: 2px solid #ffffff; outline-offset: 2px; }
    .page-links { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 20px; }
    .page-link, .back-link { display: inline-flex; align-items: center; min-height: 36px; padding: 8px 12px; border: 1px solid rgba(255,255,255,.35); border-radius: 6px; color: white; text-decoration: none; font-size: 13px; font-weight: 700; background: rgba(255,255,255,.10); }
    .page-link:hover, .back-link:hover { background: rgba(255,255,255,.18); }
    .kpi-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; padding: 18px 40px 10px; background: #e9eef5; }
    .kpi-card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px 18px; box-shadow: 0 1px 2px rgba(16,42,67,.06); }
    .kpi-label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; font-weight: 700; }
    .kpi-value { margin-top: 8px; font-size: 30px; font-weight: 800; color: var(--nav); }
    .kpi-footnote { margin: 0; padding: 0 40px 18px; background: #e9eef5; border-bottom: 1px solid var(--line); color: var(--muted); font-size: 12px; line-height: 1.45; }
    .executive-card { margin: 18px 40px 0; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px 20px; box-shadow: 0 1px 2px rgba(16,42,67,.06); }
    .executive-card h2 { margin: 0 0 10px; font-size: 18px; color: var(--nav); }
    .executive-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 0; padding: 0; list-style: none; }
    .executive-list li { border-left: 3px solid var(--blue); padding-left: 12px; color: #344054; font-size: 13px; line-height: 1.45; }
    .sticky-nav { position: sticky; top: 0; z-index: 20; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 10px 40px; background: rgba(255,255,255,.96); border-bottom: 1px solid var(--line); box-shadow: 0 1px 4px rgba(16,42,67,.08); backdrop-filter: blur(8px); }
    .sticky-nav a { color: #1f4e79; text-decoration: none; font-size: 13px; font-weight: 700; padding: 8px 10px; border-radius: 6px; }
    .sticky-nav a:hover { background: #e7f0fa; }
    main { padding: 28px 40px 46px; display: grid; gap: 32px; }
    .screen { min-height: calc(100vh - 90px); background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 24px; box-shadow: 0 1px 2px rgba(16,42,67,.06); scroll-margin-top: 72px; }
    .screen h2 { margin: 0 0 10px; font-size: 22px; color: var(--nav); letter-spacing: 0; }
    .note { color: var(--muted); font-size: 14px; max-width: 980px; line-height: 1.5; margin: 0 0 18px; }
    .plot { width: 100%; height: 560px; }
    .plot.frequency-plot { height: 620px; }
    .legend { display: flex; flex-wrap: wrap; gap: 10px; margin: 8px 0 18px; }
    .legend-item { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
    .legend-chip { display: inline-flex; min-width: 48px; justify-content: center; border-radius: 4px; padding: 4px 7px; font-weight: 800; font-size: 11px; }
    .table-wrap { overflow-x: auto; margin-top: 16px; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; background: white; }
    th, td { border: 1px solid #e1e6ee; padding: 7px 8px; text-align: center; vertical-align: top; }
    th { background: #eef3f8; color: #26384f; }
    td:first-child, td:nth-child(2) { text-align: left; font-weight: 600; }
    .focus-row td { background: #fff7ed; }
    .pass { background: #d8f3dc; color: #1b5e20; font-weight: 700; }
    .warn { background: #fff3cd; color: #7a4f00; font-weight: 700; }
    .fail { background: #f8d7da; color: #842029; font-weight: 700; }
    .info { background: #dbeafe; color: #1e40af; font-weight: 700; }
    .bar-row { display: grid; grid-template-columns: minmax(180px, 260px) 1fr 42px; gap: 12px; align-items: center; margin: 9px 0; font-size: 13px; }
    .bar-row span { overflow-wrap: anywhere; }
    .bar-track { height: 14px; background: #e8edf4; border-radius: 999px; overflow: hidden; }
    .bar { height: 100%; background: var(--blue); }
    .asset-row { display: grid; grid-template-columns: 150px 1fr minmax(200px, 280px); gap: 12px; align-items: center; margin: 12px 0; font-size: 13px; }
    .asset-row label { font-weight: 700; color: #26384f; }
    .asset-row em { color: var(--muted); font-style: normal; overflow-wrap: anywhere; }
    .insight-card { margin: 16px 0 0; padding: 13px 15px; border: 1px solid #dbe7f3; border-radius: 8px; background: #f8fbff; color: #344054; font-size: 13px; line-height: 1.45; }
    .stack { height: 22px; display: flex; overflow: hidden; border-radius: 5px; background: #e8edf4; }
    .seg.compliant { background: #52b788; }
    .seg.warning { background: #f2c94c; }
    .seg.regulatory_ambiguous { background: #60a5fa; }
    .seg.not_reportable { background: #94a3b8; }
    .seg.noncompliant { background: #e76f51; }
    .frontier-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin: 20px 0 18px; }
    .frontier-card { border: 1px solid var(--line); border-radius: 8px; padding: 16px; background: #fbfcfe; box-shadow: 0 1px 2px rgba(16,42,67,.05); }
    .frontier-card h3 { margin: 0 0 8px; color: var(--nav); font-size: 18px; }
    .frontier-card .event-title { color: #344054; font-weight: 700; line-height: 1.35; min-height: 38px; }
    .frontier-card .meta { display: grid; gap: 8px; margin: 14px 0; }
    .frontier-card .note-card { color: var(--muted); font-size: 13px; line-height: 1.45; margin: 0; }
    .frontier-matrix { margin: 18px 0; }
    .methodology-footer { margin: 0 40px 36px; padding: 18px 20px; background: #ffffff; border: 1px solid var(--line); border-radius: 8px; color: #344054; font-size: 13px; line-height: 1.5; box-shadow: 0 1px 2px rgba(16,42,67,.05); }
    .methodology-footer h2 { margin: 0 0 8px; font-size: 18px; color: var(--nav); }
    .methodology-footer p { margin: 0 0 10px; }
    .methodology-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
    .methodology-meta span { background: #eef3f8; border: 1px solid #d9e0ea; border-radius: 999px; padding: 5px 9px; color: #344054; }
    .badge { display: inline-flex; width: fit-content; max-width: 100%; padding: 4px 8px; border-radius: 999px; font-size: 11px; line-height: 1.2; font-weight: 800; text-transform: uppercase; overflow-wrap: anywhere; }
    .badge.noncompliant { background: #f8d7da; color: var(--red); }
    .badge.warning { background: #fff3cd; color: var(--yellow); }
    .badge.pass, .badge.compliant, .badge.in-scope, .badge.yes, .badge.yes-functional-not-legal { background: #d8f3dc; color: var(--green); }
    .badge.no { background: #f8d7da; color: var(--red); }
    .badge.partial { background: #fff3cd; color: var(--yellow); }
    .badge.regulatory-ambiguous, .badge.ambiguous, .badge.conditional, .badge.conditional-event-contract { background: #dbeafe; color: #1e40af; }
    .badge.out-of-scope, .badge.not-reportable, .badge.not-reportable-event-contract { background: #e4e7ec; color: var(--slate); }
    .badge.regulatory-ambiguous-event-contract { background: #ede9fe; color: #5b21b6; }
    @media (max-width: 1000px) {
      .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 16px 20px; }
      header, .sticky-nav, main { padding-left: 20px; padding-right: 20px; }
      .executive-card, .methodology-footer { margin-left: 20px; margin-right: 20px; }
      .executive-list { grid-template-columns: 1fr; }
      .frontier-grid { grid-template-columns: 1fr; }
      .asset-row { grid-template-columns: 1fr; }
    }
    @media (max-width: 640px) {
      .header-top { align-items: flex-start; flex-direction: column; }
      header h1 { font-size: 24px; }
      .kpi-grid { grid-template-columns: 1fr; }
      .screen { padding: 18px; }
      .bar-row { grid-template-columns: 1fr 1fr 34px; }
    }
    @media print {
      nav, .page-links, .language-toggle { display: none !important; }
      body { background: white; }
      header { background: #102a43 !important; }
      .screen, section, .executive-card, .methodology-footer { page-break-inside: avoid; box-shadow: none; }
      .screen { min-height: auto; }
      main { padding-top: 18px; }
    }
    """


def dashboard_plot_script(
    plotly_x: list[str],
    plotly_y: list[str],
    plotly_z: list[list[float]],
    plotly_text: list[list[str]],
    plotly_hover: list[list[str]],
    plotly_hover_en: list[list[str]],
    rule_labels: list[str],
    rule_values: list[int],
    asset_labels: list[str],
    asset_series: dict[str, list[int]],
) -> str:
    data_script = "\n".join(
        [
            f"const heatmapX = {json.dumps(plotly_x)};",
            f"const heatmapY = {json.dumps(plotly_y)};",
            f"const heatmapZ = {json.dumps(plotly_z)};",
            f"const heatmapText = {json.dumps(plotly_text)};",
            f"const heatmapHover = {{ zh: {json.dumps(plotly_hover)}, en: {json.dumps(plotly_hover_en)} }};",
            f"const ruleLabels = {json.dumps(rule_labels)};",
            f"const ruleValues = {json.dumps(rule_values)};",
            f"const assetLabels = {json.dumps(asset_labels)};",
            f"const assetSeries = {json.dumps(asset_series)};",
        ]
    )
    return (
        data_script
        + """

    const layoutBase = {
      paper_bgcolor: 'white',
      plot_bgcolor: 'white',
      font: { family: 'Arial, sans-serif', size: 12, color: '#17202a' },
      margin: { l: 90, r: 30, t: 25, b: 80 }
    };

    const plotCopy = {
      zh: {
        findingCount: '发现项数量',
        tradeCount: '交易数量',
        assetStatusLabels: {
          COMPLIANT: '合规',
          WARNING: '警告',
          NONCOMPLIANT: '不合规',
          REGULATORY_AMBIGUOUS: '条件型',
          NOT_REPORTABLE: '不可申报'
        }
      },
      en: {
        findingCount: 'Finding count',
        tradeCount: 'Trade count',
        assetStatusLabels: {
          COMPLIANT: 'Compliant',
          WARNING: 'Warning',
          NONCOMPLIANT: 'Non-compliant',
          REGULATORY_AMBIGUOUS: 'Conditional',
          NOT_REPORTABLE: 'Not reportable'
        }
      }
    };

    window.renderDashboardPlots = function renderDashboardPlots(lang = 'zh') {
      if (!window.Plotly) return;
      const copy = plotCopy[lang] || plotCopy.zh;
      const heatmapEl = document.getElementById('plot-heatmap');
      if (heatmapEl) {
        Plotly.react('plot-heatmap', [{
          type: 'heatmap',
          x: heatmapX,
          y: heatmapY,
          z: heatmapZ,
          text: heatmapText,
          customdata: heatmapHover[lang] || heatmapHover.zh,
          hovertemplate: '%{customdata}<extra></extra>',
          colorscale: [[0, '#d8f3dc'], [0.25, '#dbeafe'], [0.5, '#fff3cd'], [1, '#f8d7da']],
          zmin: 0,
          zmax: 2,
          showscale: false
        }], {
          ...layoutBase,
          height: 560,
          yaxis: { autorange: 'reversed' },
          xaxis: { tickangle: -35 }
        }, { responsive: true, displayModeBar: false });
      }

      const errorEl = document.getElementById('plot-errors');
      if (errorEl) {
        Plotly.react('plot-errors', [{
          type: 'bar',
          x: ruleValues,
          y: ruleLabels,
          orientation: 'h',
          marker: { color: '#2458a6' },
          hovertemplate: '%{y}: %{x}<extra></extra>'
        }], {
          ...layoutBase,
          height: 620,
          margin: { l: 210, r: 30, t: 25, b: 70 },
          yaxis: { automargin: true, autorange: 'reversed' },
          xaxis: { title: copy.findingCount }
        }, { responsive: true, displayModeBar: false });
      }

      const assetEl = document.getElementById('plot-assets');
      if (assetEl) {
        const assetTraces = Object.entries(assetSeries).map(([status, values]) => ({
          type: 'bar',
          name: copy.assetStatusLabels[status] || status,
          x: assetLabels,
          y: values
        }));
        Plotly.react('plot-assets', assetTraces, {
          ...layoutBase,
          height: 560,
          barmode: 'stack',
          yaxis: { title: copy.tradeCount },
          xaxis: { tickangle: -20 },
          colorway: ['#52b788', '#f2c94c', '#60a5fa', '#94a3b8', '#e76f51']
        }, { responsive: true, displayModeBar: false });
      }
    };
  """
    )


def dashboard_i18n_script() -> str:
    return """
    const DASHBOARD_LANGUAGE_KEY = 'otc-compliance-dashboard-language';

    function normalizeDashboardLanguage(lang) {
      return lang === 'en' ? 'en' : 'zh';
    }

    function savedDashboardLanguage() {
      try {
        return normalizeDashboardLanguage(window.localStorage.getItem(DASHBOARD_LANGUAGE_KEY));
      } catch (_error) {
        return 'zh';
      }
    }

    function setDashboardText(element, lang) {
      const key = lang === 'en' ? 'i18nEn' : 'i18nZh';
      if (element.dataset[key] !== undefined) {
        element.textContent = element.dataset[key];
      }
    }

    function applyDashboardLanguage(lang) {
      const activeLang = normalizeDashboardLanguage(lang);
      document.documentElement.lang = activeLang === 'en' ? 'en' : 'zh-CN';
      document.body.dataset.lang = activeLang;

      document.querySelectorAll('[data-i18n-zh][data-i18n-en]').forEach((element) => {
        setDashboardText(element, activeLang);
      });

      document.querySelectorAll('[data-lang-target]').forEach((button) => {
        const isActive = button.dataset.langTarget === activeLang;
        button.classList.toggle('is-active', isActive);
        button.setAttribute('aria-pressed', String(isActive));
      });

      const heading = document.querySelector('h1[data-i18n-zh][data-i18n-en]');
      if (heading) {
        document.title = heading.textContent;
      }

      try {
        window.localStorage.setItem(DASHBOARD_LANGUAGE_KEY, activeLang);
      } catch (_error) {
        // Local files or strict browser settings can block localStorage.
      }

      if (typeof window.renderDashboardPlots === 'function') {
        window.renderDashboardPlots(activeLang);
      }
    }

    function initDashboardLanguageToggle() {
      document.querySelectorAll('[data-lang-target]').forEach((button) => {
        button.addEventListener('click', () => applyDashboardLanguage(button.dataset.langTarget));
      });
      applyDashboardLanguage(savedDashboardLanguage());
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initDashboardLanguageToggle);
    } else {
      initDashboardLanguageToggle();
    }
    """


def dashboard_shell(
    title: str,
    subtitle: str,
    body: str,
    script: str,
    header_links: str = "",
    plotly_src: str = "assets/plotly.min.js",
    title_en: str | None = None,
    subtitle_en: str | None = None,
) -> str:
    title_en = title if title_en is None else title_en
    subtitle_en = subtitle if subtitle_en is None else subtitle_en
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <script src="{html.escape(plotly_src)}"></script>
  <style>{dashboard_css()}</style>
</head>
<body>
  <header>
    <div class="header-top">
      {i18n_element("div", "个人 RegTech 产品原型 · 张钧诒", "Personal RegTech Product Prototype · Zhang Junyi", 'class="eyebrow"')}
      <div class="language-toggle" role="group" aria-label="Language">
        <button type="button" class="lang-button is-active" data-lang-target="zh" aria-pressed="true">中文</button>
        <button type="button" class="lang-button" data-lang-target="en" aria-pressed="false">EN</button>
      </div>
    </div>
    {i18n_element("h1", title, title_en)}
    {i18n_element("p", subtitle, subtitle_en)}
    {header_links}
  </header>
  {body}
  <script>
  {script}
  {dashboard_i18n_script()}
  </script>
</body>
</html>
"""


def write_dashboard(path: Path, results: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    ensure_plotly_bundle(path.parent)
    requested_regimes = [
        str(regime).upper()
        for regime in results.get("metadata", {}).get("regimes", [])
        if str(regime).strip()
    ]
    if not requested_regimes:
        requested_regimes = ["CFTC", "MAS"]
    regime_label = " / ".join(requested_regimes)
    second_regime = next((regime for regime in requested_regimes if regime != "CFTC"), requested_regimes[-1])
    rule_columns = [
        ("PARSE", "PARSE"),
        ("UPI", "UPI"),
        ("LEI", "LEI"),
        ("UTI", "UTI"),
        ("TIMESTAMP", "TIMESTAMP"),
        ("CURRENCY", "CURRENCY"),
        ("MARGIN", "MARGIN"),
        *[(regime, regime) for regime in requested_regimes],
        ("FRONTIER", "EVENT"),
    ]
    status_score = {"PASS": 0, "INFO": 0.5, "WARN": 1, "FAIL": 2}
    plotly_x = [name for name, _ in rule_columns]
    plotly_y = []
    plotly_z = []
    plotly_text = []
    plotly_hover = []
    plotly_hover_en = []
    heatmap_rows = []

    def heatmap_sort_key(trade: dict[str, Any]) -> tuple[int, str]:
        if trade["trade_id"] == "T027":
            return (4, trade["trade_id"])
        if trade["classification_conclusion"] == "CONDITIONAL_EVENT_CONTRACT":
            return (3, trade["trade_id"])
        if trade["overall_status"] == "NONCOMPLIANT":
            return (0, trade["trade_id"])
        if trade["overall_status"] == "WARNING":
            return (1, trade["trade_id"])
        return (2, trade["trade_id"])

    ordered_trades = sorted(results["trades"], key=heatmap_sort_key)
    for trade in ordered_trades:
        parse_cell = "FAIL" if trade["parse"]["parse_status"] == "FAILED" else "WARN" if trade["parse"]["parse_status"] == "PARTIAL" else "PASS"
        row_statuses = [parse_cell]
        row_hover = [heatmap_hover_text(trade, "PARSE", parse_cell)]
        row_hover_en = [heatmap_hover_text(trade, "PARSE", parse_cell, "en")]
        cells = [f"<td>{html.escape(trade['trade_id'])}</td>", f"<td>{html.escape(str(trade['asset_class']))}</td>", dashboard_cell(parse_cell)]
        for family, fragment in rule_columns[1:]:
            status = severity_for_rule(trade, fragment)
            row_statuses.append(status)
            row_hover.append(heatmap_hover_text(trade, family, status))
            row_hover_en.append(heatmap_hover_text(trade, family, status, "en"))
            cells.append(dashboard_cell(status))
        row_class = " class='focus-row'" if trade["trade_id"] == "T027" else ""
        heatmap_rows.append(f"<tr{row_class}>" + "".join(cells) + "</tr>")
        plotly_y.append(trade["trade_id"])
        plotly_z.append([status_score[item] for item in row_statuses])
        plotly_text.append(row_statuses)
        plotly_hover.append(row_hover)
        plotly_hover_en.append(row_hover_en)

    rule_counts: Counter[str] = Counter()
    scope_counts: Counter[str] = Counter()
    caveat_counts: Counter[str] = Counter()
    for trade in results["trades"]:
        for item in trade["findings"]:
            if item.get("finding_type") == SCOPE_FINDING:
                scope_counts[item["rule_id"]] += 1
                continue
            if item.get("severity") == "INFO" or item.get("rule_id") in {
                "UPI_PLACEHOLDER",
                "UPI_TEMPLATE_MAPPING",
                "REFERENCE_RATE_ALIAS",
            }:
                caveat_counts[item["rule_id"]] += 1
            else:
                rule_counts[item["rule_id"]] += 1
    max_rule_count = max(rule_counts.values(), default=1)
    rule_items = rule_counts.most_common()
    rule_labels = [rule_id for rule_id, _ in rule_items]
    rule_values = [count for _, count in rule_items]
    bars = []
    for rule_id, count in rule_items:
        width = int((count / max_rule_count) * 100)
        bars.append(
            f"<div class='bar-row'><span>{html.escape(rule_id)}</span><div class='bar-track'><div class='bar' style='width:{width}%'></div></div><b>{count}</b></div>"
        )
    caveat_rows = []
    for rule_id, count in caveat_counts.most_common():
        caveat_rows.append(f"<tr><td>{html.escape(rule_id)}</td><td>{count}</td></tr>")
    caveat_table = ""
    if caveat_rows:
        caveat_table = (
            f"{i18n_element('h3', '数据说明与归一化备注', 'Data Notes and Normalization Caveats')}"
            f"{i18n_element('p', '这些 INFO 级备注仍保留在交易明细中，但从主频次图中分离，避免确定性归一化掩盖实质合规发现。', 'These INFO-level notes remain in trade details, but are separated from the main frequency chart so deterministic normalization does not obscure substantive compliance findings.', 'class=\"note\"')}"
            f"<div class='table-wrap'><table><thead><tr>{i18n_th('规则', 'Rule')}{i18n_th('数量', 'Count')}</tr></thead>"
            f"<tbody>{''.join(caveat_rows)}</tbody></table></div>"
        )

    scope_rows = [
        f"<tr><td>{html.escape(rule_id)}</td><td>{count}</td></tr>"
        for rule_id, count in scope_counts.most_common()
    ]
    scope_table = ""
    if scope_rows:
        scope_table = (
            f"{i18n_element('h3', '报告范围判断', 'Reporting Scope Judgments')}"
            f"{i18n_element('p', '范围标记单独展示，因为 jurisdictional scope 不等同于字段级合规错误。', 'Scope markers are shown separately because jurisdictional scope is not the same as a field-level compliance error.', 'class=\"note\"')}"
            f"<div class='table-wrap'><table><thead><tr>{i18n_th('范围规则', 'Scope rule')}{i18n_th('数量', 'Count')}</tr></thead>"
            f"<tbody>{''.join(scope_rows)}</tbody></table></div>"
        )

    asset_rows = []
    asset_labels = sorted(results["summary"]["asset_class_status_counts"])
    status_labels = [
        "COMPLIANT",
        "WARNING",
        "NONCOMPLIANT",
        "REGULATORY_AMBIGUOUS",
        "NOT_REPORTABLE",
    ]
    asset_series = {
        raw_status: [
            results["summary"]["asset_class_status_counts"].get(asset, {}).get(raw_status, 0)
            for asset in asset_labels
        ]
        for raw_status in status_labels
    }
    for asset, counts in results["summary"]["asset_class_status_counts"].items():
        total = sum(counts.values()) or 1
        segments = []
        for status in ["COMPLIANT", "WARNING", "NONCOMPLIANT", "REGULATORY_AMBIGUOUS", "NOT_REPORTABLE"]:
            value = counts.get(status, 0)
            if value:
                segments.append(f"<span class='seg {status.lower()}' style='width:{(value / total) * 100:.2f}%' title='{status}: {value}'></span>")
        asset_rows.append(
            f"<div class='asset-row'><label>{html.escape(asset)}</label><div class='stack'>{''.join(segments)}</div><em>{html.escape(str(dict(counts)))}</em></div>"
        )
    asset_totals = {
        asset: sum(counts.values())
        for asset, counts in results["summary"]["asset_class_status_counts"].items()
    }
    largest_asset = max(asset_totals, key=asset_totals.get) if asset_totals else "N/A"
    event_counts = results["summary"]["asset_class_status_counts"].get(EVENT_ASSET_CLASS, {})
    event_total = sum(event_counts.values()) or 1
    event_frontier_count = event_counts.get("REGULATORY_AMBIGUOUS", 0) + event_counts.get("NOT_REPORTABLE", 0)
    event_frontier_share = round((event_frontier_count / event_total) * 100)
    asset_insight = (
        f"{largest_asset} 是交易数量最高的资产类别；EventContract 的分类边界集中度最高 "
        f"({event_frontier_count}/{event_total}, {event_frontier_share}%)。"
        "这说明组合交易量和监管前沿风险是两种不同视角。"
    )
    asset_insight_en = (
        f"{largest_asset} has the largest trade count; EventContract has the highest concentration of classification-frontier cases "
        f"({event_frontier_count}/{event_total}, {event_frontier_share}%). "
        "This separates portfolio volume from frontier regulatory risk."
    )

    total_trades = results["metadata"].get("trade_count", len(results["trades"]))
    overall_counts = results["summary"]["overall_status_counts"]
    data_quality_counts = results["summary"]["data_quality_status_counts"]
    severity_counts = results["summary"]["severity_counts"]
    event_contract_count = sum(1 for trade in results["trades"] if trade["asset_class"] == EVENT_ASSET_CLASS)
    kpi_cards = [
        ("交易总数", "Total trades", total_trades),
        ("兼容口径不合规交易", "Legacy non-compliant trades", overall_counts.get("NONCOMPLIANT", 0)),
        ("数据质量不合规记录", "Data-quality non-compliant records", data_quality_counts.get("NONCOMPLIANT", 0)),
        ("兼容口径警告交易", "Legacy warning trades", overall_counts.get("WARNING", 0)),
        ("数据质量警告记录", "Data-quality warning records", data_quality_counts.get("WARNING", 0)),
        ("事件合约", "Event contracts", event_contract_count),
        ("不合规发现项", "Non-compliant findings", severity_counts.get("NONCOMPLIANT", 0)),
    ]
    kpi_parts = []
    for label_zh, label_en, value in kpi_cards:
        label_html = i18n_element("div", label_zh, label_en, 'class="kpi-label"')
        kpi_parts.append(f"<article class='kpi-card'>{label_html}<div class='kpi-value'>{value}</div></article>")
    kpi_html = "".join(kpi_parts)
    margin_phrase = f"{second_regime} null margin 违规" if second_regime in {"EMIR", "MAS"} else "null margin 违规"
    margin_phrase_en = f"{second_regime} null margin breaches" if second_regime in {"EMIR", "MAS"} else "null margin breaches"
    executive_items = [
        (
            f"主要实质问题集中在标识符和监管字段，尤其是 LEI check digit failure 与 {margin_phrase}。",
            f"The main substantive issues cluster around identifiers and reporting fields, especially LEI check digit failures and {margin_phrase_en}.",
        ),
        (
            "T026-T028 不是 parser failure；它们暴露的是 EventContract 缺少 ANNA-DSB OTC product definition 的 taxonomy gap。",
            "T026-T028 are not parser failures; they expose the taxonomy gap where EventContract products lack ANNA-DSB OTC product definitions.",
        ),
        (
            "T027 按案例事实不在所选 OTC reporting path 内，但仍因缺少 LEI/UTI 和 USDC settlement 被标记为数据质量不合规。",
            "T027 is outside the selected OTC reporting path on the case facts, but remains data-quality non-compliant because LEI/UTI identifiers are missing and settlement uses USDC.",
        ),
    ]
    executive_list = "".join(i18n_element("li", item_zh, item_en) for item_zh, item_en in executive_items)
    executive_html = f"""
  <section class="executive-card" aria-label="管理层解读">
    {i18n_element("h2", "管理层解读", "Executive Readout")}
    <ul class="executive-list">
      {executive_list}
    </ul>
  </section>
  """

    frontier_rows = []
    frontier_cards = []
    frontier_matrix_rows = []
    economic_function_rows = []
    supervisory_action_rows = []
    exposure_labels = {
        "T026": "German election subsidy risk",
        "T027": "CPI / USD bond exposure",
        "T028": "ESMA AI Act compliance cost",
    }
    frontier_card_copy = {
        "T026": {
            "title_zh": "T026 - 条件型事件合约",
            "title_en": "T026 - Conditional Event Contract",
            "platform": "Kalshi / CFTC DCM",
            "issue_zh": "缺少 OTC UPI taxonomy",
            "issue_en": "Missing OTC UPI taxonomy",
            "why_zh": "存在经济对冲功能，但普通 OTC reporting route 不完整。",
            "why_en": "It has an economic hedging function, but the ordinary OTC reporting route is incomplete.",
        },
        "T027": {
            "title_zh": "T027 - 不可申报但可见性风险高",
            "title_en": "T027 - Not Reportable, High Visibility Risk",
            "platform": "Polymarket / offshore",
            "issue_zh": "缺少 LEI、UTI，采用 USDC settlement，且无 CFTC DCM status",
            "issue_en": "Missing LEI and UTI, USDC settlement, and no CFTC DCM status",
            "why_zh": "经济功能类似对冲，但普通 CFTC/EMIR OTC reporting path 无法看见。",
            "why_en": "It can resemble a hedge economically, but the ordinary CFTC/EMIR OTC reporting path cannot see it.",
        },
        "T028": {
            "title_zh": "T028 - 条件型事件合约",
            "title_en": "T028 - Conditional Event Contract",
            "platform": "Kalshi / CFTC DCM",
            "issue_zh": "监管事件 underlier，缺少 OTC UPI taxonomy",
            "issue_en": "Regulatory-event underlier without OTC UPI taxonomy",
            "why_zh": "政策风险对冲场景没有传统 OTC product taxonomy。",
            "why_en": "The policy-risk hedging scenario does not have a traditional OTC product taxonomy.",
        },
    }
    for trade in results["trades"]:
        if trade["asset_class"] == EVENT_ASSET_CLASS:
            notes = event_regulatory_note(trade)
            source_facts = trade.get("source_facts") or {}
            event_title = source_facts.get("event_description") or trade.get("use_case") or "Event contract"
            platform = " / ".join(
                str(item).replace("_", " ")
                for item in [source_facts.get("platform"), source_facts.get("platform_type")]
                if item
            )
            cftc_status = source_facts.get("case_file_cftc_status") or trade.get("reporting_scope_status")
            second_status = source_facts.get(f"case_file_{second_regime.lower()}_status")
            if not second_status:
                second_status = next(
                    (
                        item.get("status")
                        for item in trade.get("scope_assessments", [])
                        if item.get("regime") == second_regime
                    ),
                    "NOT_ASSESSED",
                )
            if trade["upi"].get("upi_status") == "NO_PRODUCT_DEFINITION":
                upi_taxonomy_zh = "缺少产品定义"
                upi_taxonomy_en = "Missing product definition"
            else:
                upi_status = str(trade["upi"].get("upi_status", "Unknown"))
                upi_taxonomy_zh = upi_status
                upi_taxonomy_en = upi_status
            if trade["trade_id"] == "T027":
                engine_conclusion_zh = "报告范围外，但数据质量不合规"
                engine_conclusion_en = "Out of scope, but data-quality non-compliant"
            else:
                engine_conclusion_en = str(trade["classification_conclusion"]).replace("_", " ").title()
                engine_conclusion_zh = engine_conclusion_en
            platform_label = i18n_span("平台:", "Platform:")
            regulatory_label = i18n_span("监管结论", "Regulatory conclusion")
            quality_label = i18n_span("数据质量", "Data quality")
            scope_label = i18n_span("报告范围", "Reporting scope")
            issue_label = i18n_span("核心问题:", "Core issue:")
            meaning_label = i18n_span("产品意义:", "Product meaning:")
            card = frontier_card_copy[trade["trade_id"]]
            frontier_cards.append(
                "<article class='frontier-card'>"
                f"{i18n_element('h3', card['title_zh'], card['title_en'])}"
                f"<div class='event-title'>{platform_label} {html.escape(card['platform'])}</div>"
                "<div class='meta'>"
                f"<span>{regulatory_label} {dashboard_badge(trade['classification_conclusion'])}</span>"
                f"<span>{quality_label} {dashboard_badge(trade['data_quality_status'])}</span>"
                f"<span>{scope_label} {dashboard_badge(trade['reporting_scope_status'])}</span>"
                "</div>"
                f"<p class='note-card'><b>{issue_label}</b> {i18n_span(card['issue_zh'], card['issue_en'])}<br><b>{meaning_label}</b> {i18n_span(card['why_zh'], card['why_en'])}</p>"
                "</article>"
            )
            frontier_rows.append(
                "<tr>"
                f"<td>{html.escape(trade['trade_id'])}</td>"
                f"<td>{html.escape(str(trade['use_case']))}</td>"
                f"<td>{html.escape(trade['classification_conclusion'])}</td>"
                f"<td>{html.escape(trade['data_quality_status'])}</td>"
                f"<td>{html.escape(trade['reporting_scope_status'])}</td>"
                f"<td>{html.escape(notes)}</td>"
                "</tr>"
            )
            frontier_matrix_rows.append(
                "<tr>"
                f"<td>{html.escape(trade['trade_id'])}</td>"
                f"<td>{html.escape(platform)}</td>"
                f"<td>{html.escape(exposure_labels.get(trade['trade_id'], str(event_title)))}</td>"
                f"<td>{i18n_span(str(upi_taxonomy_zh), str(upi_taxonomy_en))}</td>"
                f"<td>{html.escape(str(cftc_status).replace('_', ' ').title())}</td>"
                f"<td>{html.escape(str(second_status).replace('_', ' ').title())}</td>"
                f"<td>{i18n_span(engine_conclusion_zh, engine_conclusion_en)}</td>"
                "</tr>"
            )
            economic_test = trade.get("economic_function_test") or {}
            if economic_test:
                economic_function_rows.append(
                    "<tr>"
                    f"<td>{html.escape(trade['trade_id'])}</td>"
                    f"<td>{dashboard_badge(economic_test['quantifiable_exposure']['status'])}</td>"
                    f"<td>{dashboard_badge(economic_test['viable_hedge_substitute']['status'])}</td>"
                    f"<td>{dashboard_badge(economic_test['price_discovery_beyond_public_data']['status'])}</td>"
                    f"<td>{dashboard_badge(economic_test['engine_conclusion'])}</td>"
                    "</tr>"
                )
            flags = trade.get("supervisory_flags") or {}
            if flags:
                supervisory_action_rows.append(
                    "<tr>"
                    f"<td>{html.escape(trade['trade_id'])}</td>"
                    f"<td>{html.escape(str(flags.get('no_upi_taxonomy')))}</td>"
                    f"<td>{html.escape(str(flags.get('non_iso_settlement_currency')))}</td>"
                    f"<td>{html.escape(str(flags.get('missing_identifier_visibility')))}</td>"
                    f"<td>{html.escape(str(flags.get('ec1_threshold_status')))}</td>"
                    f"<td>{html.escape(str(flags.get('recommended_cftc_action')))}</td>"
                    "</tr>"
                )

    heatmap_section = f"""
    <section id="heatmap" class="screen">
      {i18n_element("h2", "合规热力图", "Compliance Heatmap")}
      {i18n_element("p", "每一行是一笔交易，每一列是一类校验控制。传统不合规交易优先展示，其后是警告、通过、条件型事件合约，以及被突出标记的 T027 可见性风险案例。", "Each row is a trade and each column is a validation control family. Traditional non-compliant trades appear first, followed by warnings, passes, conditional event contracts, and the highlighted T027 visibility-risk case.", 'class="note"')}
      <div class="legend" aria-label="热力图图例">
        <span class="legend-item"><span class="legend-chip pass">PASS</span> {i18n_span("无明显问题", "No material issue")}</span>
        <span class="legend-item"><span class="legend-chip info">INFO</span> {i18n_span("归一化 / 范围说明", "Normalization / scope note")}</span>
        <span class="legend-item"><span class="legend-chip warn">WARN</span> {i18n_span("警告 / 边界情形", "Warning / boundary case")}</span>
        <span class="legend-item"><span class="legend-chip fail">FAIL</span> {i18n_span("不合规", "Non-compliant")}</span>
      </div>
      <div id="plot-heatmap" class="plot"></div>
      <div class="table-wrap">
        <table>
          <thead><tr>{i18n_th("交易", "Trade")}{i18n_th("资产类别", "Asset class")}{''.join(f'<th>{name}</th>' for name, _ in rule_columns)}</tr></thead>
          <tbody>{''.join(heatmap_rows)}</tbody>
        </table>
      </div>
    </section>
    """
    frequency_section = f"""
    <section id="frequency" class="screen">
      {i18n_element("h2", "验证规则发现频次", "Validation Finding Frequency")}
      {i18n_element("p", "报告范围判断单独展示，因为 jurisdictional scope 不等同于字段级合规错误。", "Reporting-scope judgments are shown separately because jurisdictional scope is not the same as a field-level compliance error.", 'class="note"')}
      <div id="plot-errors" class="plot frequency-plot"></div>
      {''.join(bars)}
      {scope_table}
      {caveat_table}
    </section>
    """
    assets_section = f"""
    <section id="assets" class="screen">
      {i18n_element("h2", "资产类别分布", "Asset Class Breakdown")}
      {i18n_element("p", "堆叠视图按资产类别展示 compliant、warning、non-compliant、conditional 和 not-reportable 记录分布。", "The stacked view shows compliant, warning, non-compliant, conditional, and not-reportable records by asset class.", 'class="note"')}
      <div id="plot-assets" class="plot"></div>
      {i18n_element("div", asset_insight, asset_insight_en, 'class="insight-card"')}
      {''.join(asset_rows)}
    </section>
    """
    frontier_section = f"""
    <section id="frontier" class="screen">
      {i18n_element("h2", "事件合约分类边界", "Event Contract Classification Frontier")}
      {i18n_element("p", "T026-T028 单独展示，因为事件合约可以转移经济风险，却不一定落入普通 OTC UPI taxonomy。卡片展示的是监管解释，而不只是原始字段。", "T026-T028 are shown separately because event contracts can transfer economic risk without necessarily fitting the ordinary OTC UPI taxonomy. The cards show the regulatory interpretation, not just raw fields.", 'class="note"')}
      <div class="frontier-grid">{''.join(frontier_cards)}</div>
      <div class="table-wrap frontier-matrix">
        <table>
          <thead><tr>{i18n_th("交易", "Trade")}{i18n_th("平台", "Platform")}{i18n_th("经济风险敞口", "Economic exposure")}{i18n_th("UPI Taxonomy", "UPI Taxonomy")}<th>CFTC</th><th>{html.escape(second_regime)}</th>{i18n_th("引擎结论", "Engine conclusion")}</tr></thead>
          <tbody>{''.join(frontier_matrix_rows)}</tbody>
        </table>
      </div>
      {i18n_element("h3", "经济功能测试", "Economic Function Test")}
      <div class="table-wrap">
        <table>
          <thead><tr>{i18n_th("交易", "Trade")}{i18n_th("可量化敞口", "Quantifiable exposure")}{i18n_th("对冲替代性", "Hedge substitutability")}{i18n_th("增量价格发现", "Incremental price discovery")}{i18n_th("引擎结论", "Engine conclusion")}</tr></thead>
          <tbody>{''.join(economic_function_rows)}</tbody>
        </table>
      </div>
      {i18n_element("h3", "CFTC 监管动作标记", "CFTC Supervisory Action Flags")}
      <div class="table-wrap">
        <table>
          <thead><tr>{i18n_th("交易", "Trade")}{i18n_th("缺少 UPI Taxonomy", "Missing UPI taxonomy")}{i18n_th("非 ISO 结算", "Non-ISO settlement")}{i18n_th("标识符缺口", "Identifier gap")}{i18n_th("EC-1 阈值", "EC-1 threshold")}{i18n_th("建议动作", "Recommended action")}</tr></thead>
          <tbody>{''.join(supervisory_action_rows)}</tbody>
        </table>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr>{i18n_th("交易", "Trade")}{i18n_th("事件类型", "Event type")}{i18n_th("结论", "Conclusion")}{i18n_th("数据质量", "Data quality")}{i18n_th("范围", "Scope")}{i18n_th("监管发现", "Regulatory finding")}</tr></thead>
          <tbody>{''.join(frontier_rows)}</tbody>
        </table>
      </div>
    </section>
    """
    page_links = """
    <div class="page-links">
      {heatmap_link}
      {frequency_link}
      {asset_link}
      {frontier_link}
    </div>
    """.format(
        heatmap_link=i18n_element("a", "打开全屏热力图", "Open Full-Screen Heatmap", 'class="page-link" href="pages/compliance_heatmap.html"'),
        frequency_link=i18n_element("a", "打开全屏规则频次", "Open Full-Screen Frequency", 'class="page-link" href="pages/finding_frequency.html"'),
        asset_link=i18n_element("a", "打开全屏资产分布", "Open Full-Screen Asset Breakdown", 'class="page-link" href="pages/asset_class_breakdown.html"'),
        frontier_link=i18n_element("a", "打开全屏分类边界", "Open Full-Screen Classification Frontier", 'class="page-link" href="pages/classification_frontier.html"'),
    )
    sticky_nav = """
    <nav class="sticky-nav" aria-label="工作台分区">
      {heatmap_link}
      {frequency_link}
      {asset_link}
      {frontier_link}
    </nav>
    """.format(
        heatmap_link=i18n_element("a", "合规热力图", "Heatmap", 'href="#heatmap"'),
        frequency_link=i18n_element("a", "规则频次", "Frequency", 'href="#frequency"'),
        asset_link=i18n_element("a", "资产分布", "Assets", 'href="#assets"'),
        frontier_link=i18n_element("a", "分类边界", "Frontier", 'href="#frontier"'),
    )
    if second_regime == "MAS":
        methodology_scope = (
            "MAS validation 覆盖产品原型级 required-field、null-margin 和 Singapore-nexus 逻辑，"
            "不是完整生产级 MAS reporting implementation。"
        )
        methodology_scope_en = (
            "MAS validation covers prototype-level required-field, null-margin, and Singapore-nexus logic; "
            "it is not a complete production MAS reporting implementation."
        )
    elif second_regime == "EMIR":
        methodology_scope = (
            "EMIR validation 覆盖 required fields 和 null-margin treatment，"
            "不是完整生产级 EMIR Refit implementation。"
        )
        methodology_scope_en = (
            "EMIR validation covers required fields and null-margin treatment; "
            "it is not a complete production EMIR Refit implementation."
        )
    else:
        methodology_scope = (
            f"{second_regime} validation 是产品原型级实现，不是完整生产级 reporting implementation。"
        )
        methodology_scope_en = (
            f"{second_regime} validation is a product-prototype implementation, not a complete production reporting implementation."
        )
    product_definition_path = results.get("metadata", {}).get("product_definitions_path", "data/product_definitions")
    methodology_text = (
        f"这是个人 RegTech 产品原型。{methodology_scope} ANNA-DSB validation 检查 product-template coverage 和 selected codesets，不构造完整 UPI 申报 payload。"
    )
    methodology_text_en = (
        f"This is a personal RegTech product prototype. {methodology_scope_en} ANNA-DSB validation checks product-template coverage and selected codesets; it does not construct a full UPI reporting payload."
    )
    methodology_footer = f"""
  <footer class="methodology-footer">
    {i18n_element("h2", "方法论与边界", "Methodology and Boundaries")}
    {i18n_element("p", methodology_text, methodology_text_en)}
    <div class="methodology-meta">
      {i18n_element("span", "输入: data/processed/trades.json", "Input: data/processed/trades.json")}
      {i18n_element("span", f"监管辖区: {', '.join(requested_regimes)}", f"Regimes: {', '.join(requested_regimes)}")}
      {i18n_element("span", f"处理交易数: {total_trades}", f"Trades processed: {total_trades}")}
      {i18n_element("span", "生成脚本: run_compliance_check.py", "Generated by: run_compliance_check.py")}
      {i18n_element("span", f"产品定义: {str(product_definition_path)}", f"Product definitions: {str(product_definition_path)}")}
    </div>
  </footer>
  """
    body = f"""
  <section class="kpi-grid" aria-label="工作台 KPI">{kpi_html}</section>
  {i18n_element("p", "兼容口径 status 仍保留用于历史输出；data-quality status 将字段级合规问题与报告范围分开。", "The legacy status remains for historical output compatibility; data-quality status separates field-level compliance issues from reporting scope.", 'class="kpi-footnote"')}
  {executive_html}
  {sticky_nav}
  <main>
    {heatmap_section}
    {frequency_section}
    {assets_section}
    {frontier_section}
  </main>
  {methodology_footer}
  """
    script = dashboard_plot_script(plotly_x, plotly_y, plotly_z, plotly_text, plotly_hover, plotly_hover_en, rule_labels, rule_values, asset_labels, asset_series)
    content = dashboard_shell(
        "衍生品交易报告合规审查工作台",
        f"围绕 UPI、UTI、LEI、{html.escape(regime_label)} 字段和事件合约分类边界的规则型 RegTech 审查原型。",
        body,
        script,
        page_links,
        title_en="Derivatives Trade Reporting Compliance Review Workbench",
        subtitle_en=f"A rules-based RegTech review prototype for UPI, UTI, LEI, {html.escape(regime_label)} fields, and event-contract classification boundaries.",
    )
    path.write_text(content, encoding="utf-8")

    pages_dir = path.parent / "pages"
    ensure_dir(pages_dir)
    page_header = (
        '<div class="page-links">'
        f'{i18n_element("a", "返回主工作台", "Back to Main Dashboard", 'class="back-link" href="../dashboard.html"')}'
        '</div>'
    )
    page_specs = [
        (
            "compliance_heatmap.html",
            "合规热力图",
            "Compliance Heatmap",
            "按控制家族展示交易级验证状态的全屏视图。",
            "A full-screen view of trade-level validation status by control family.",
            f"<main>{heatmap_section}</main>",
        ),
        (
            "finding_frequency.html",
            "验证规则发现频次",
            "Validation Finding Frequency",
            "展示重复出现的数据质量与合规验证发现项的全屏视图。",
            "A full-screen view of recurring data-quality and compliance validation findings.",
            f"<main>{frequency_section}</main>",
        ),
        (
            "asset_class_breakdown.html",
            "资产类别分布",
            "Asset Class Breakdown",
            "按资产类别展示组合状态的全屏视图。",
            "A full-screen view of portfolio status by asset class.",
            f"<main>{assets_section}</main>",
        ),
        (
            "classification_frontier.html",
            "事件合约分类边界",
            "Event Contract Classification Frontier",
            "展示 T026-T028 事件合约分类处理的全屏视图。",
            "A full-screen view of the T026-T028 event-contract classification treatment.",
            f"<main>{frontier_section}</main>",
        ),
    ]
    for filename, title, title_en, subtitle, subtitle_en, page_body in page_specs:
        (pages_dir / filename).write_text(
            dashboard_shell(title, subtitle, page_body, script, page_header, "../assets/plotly.min.js", title_en=title_en, subtitle_en=subtitle_en),
            encoding="utf-8",
        )


def write_outputs(results: dict[str, Any], output_dir: Path, dashboard_dir: Path) -> None:
    ensure_dir(output_dir)
    ensure_dir(dashboard_dir)
    write_json(output_dir / "compliance_results.json", results)
    write_json(output_dir / "summary.json", {"metadata": results["metadata"], **results["summary"]})
    write_findings_csv(output_dir / "findings.csv", results)
    write_dashboard(dashboard_dir / "dashboard.html", results)


def run_pipeline(input_path: Path, product_definitions: Path, regimes: list[str], output_dir: Path, dashboard_dir: Path) -> dict[str, Any]:
    trades = load_trades(input_path)
    results = analyze_trades(trades, product_definitions, regimes)
    write_outputs(results, output_dir, dashboard_dir)
    return results
