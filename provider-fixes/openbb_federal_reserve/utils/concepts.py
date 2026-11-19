"""Build FFIEC concept metadata: full names, narratives, and value units."""

from __future__ import annotations

from typing import Any

_SMALL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "per",
    "the",
    "to",
    "vs",
    "with",
}
_ACRONYMS = {
    "TE",
    "YTD",
    "QTD",
    "FTE",
    "US",
    "USD",
    "ROA",
    "ROE",
    "ROAA",
    "ROAE",
    "CD",
    "ATM",
    "ACH",
    "HTM",
    "AFS",
    "IRA",
    "TDR",
    "OREO",
    "HELOC",
    "ALLL",
    "CECL",
    "FHLB",
    "GNMA",
    "FNMA",
    "FHLMC",
    "SBA",
    "MBS",
    "CMBS",
    "ABS",
    "REIT",
    "LIP",
    "OBS",
    "PD",
    "GAAP",
    "FDIC",
    "OCC",
    "PG",
}


_GUIDE_RESIDUAL_ABBREVIATIONS = (
    (r"\bLn&Ls\b", "Loans & Leases"),
    (r"\bQtr Ann\b", "Quarter Annualized"),
    (r"\bQtr\b", "Quarter"),
)


def clean_name(raw: str | None) -> str | None:
    """Title-case an FFIEC item name into a readable label."""
    import re

    if not raw:
        return None
    text = re.sub(r"\s+", " ", raw).strip()
    text = re.sub(
        r"\s*(?:/\s*)?(?:as\s+)?(?:a\s+)?(?:percent|%)\s+of\s+(?:average|avg)\.?"
        r"(?:\s+total)?\s+assets\b.*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s*\(\$\d*s?\)", "", text)
    text = re.sub(r"\s*\(included in .*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\(\d+\)\s*$", "", text)
    text = re.sub(r"\s*\(\*+\)", "", text).strip().rstrip(".").strip()
    seen_first = [False]

    def _case(match: re.Match[str]) -> str:
        """Case one word: acronym upper, small word lower, otherwise capitalized."""
        word = match.group(0)
        is_first = not seen_first[0]
        seen_first[0] = True
        if word.upper() in _ACRONYMS:
            return word.upper()
        if not is_first and word.lower() in _SMALL_WORDS:
            return word.lower()
        return word[:1].upper() + word[1:].lower()

    titled = re.sub(r"[A-Za-z0-9]+", _case, text)
    for pattern, full in _GUIDE_RESIDUAL_ABBREVIATIONS:
        titled = re.sub(pattern, full, titled, flags=re.IGNORECASE)
    return titled or None


def _narrative(text: str | None) -> str | None:
    """Drop the FFIEC ``Pseudo MDRM`` placeholder definitions, else pass through."""
    if not text or "pseudo mdrm" in text.lower():
        return None
    return text


def indented_name(label: str | None, name: str | None) -> str | None:
    """Reapply ``label``'s report-indentation prefix (``>`` + spaces) to ``name``."""
    import re

    if not name:
        return label
    match = re.match(r">[\s ]*", label or "")
    return (match.group(0) if match else "") + name


def _report_concept_types(section: str, cycle_ids: str | None = None) -> dict[str, str]:
    """Read explicit CDR datatype IDs from the report's period-cell metadata.

    IDs are published in /Public/Reports/MyUbprReport.js. The reference bank
    identifies the layout; its amounts are never used as report results.
    """
    import re
    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_federal_reserve.utils.ubpr_report import _post, _section_id, report_cycles

    labels = {
        "9": "Monetary", "10": "Text", "11": "Integer", "12": "Abstract",
        "17": "Boolean", "93": "Decimal", "94": "Percentage", "95": "Date",
        "96": "Ratio", "155": "Monetary", "162": "Decimal", "163": "Integer",
    }
    page_id, _ = _section_id(section, 283)
    requested = cycle_ids.split(",") if cycle_ids else [
        c["reportingcycleid"] for c in report_cycles()[:5]
    ]
    rows = []
    for start in range(0, len(requested), 5):
        batch = _post("MyUbprLinesData", {
            "ID_RSSD": "112837", "ScheduleID": page_id,
            "ReportingCycleIdList": ",".join(requested[start:start + 5]),
            "PeerDefinition": "",
        })
        if isinstance(batch, list):
            rows.extend(batch)
    types: dict[str, str] = {}
    for row in rows if isinstance(rows, list) else []:
        for key, cell in row.items():
            if not re.fullmatch(r"\d{2}_\d{2}_\d{4}", key) or not cell:
                continue
            for part in str(cell).split(", "):
                fields = part.split(";")
                if len(fields) < 2 or not fields[1].strip().strip("'"):
                    continue
                code = fields[1].strip().strip("'")
                type_id = fields[2].strip() if len(fields) > 2 else ""
                if type_id not in labels:
                    raise OpenBBError(f"Unknown FFIEC report datatype {type_id!r} for {code}; cannot safely scale values.")
                label = labels[type_id]
                if code in types and types[code] != label:
                    raise OpenBBError(f"Conflicting FFIEC report datatypes for {code}.")
                types[code] = label
    if not types:
        raise OpenBBError("FFIEC report metadata has no explicit concept datatypes; cannot safely scale values.")
    return types


def concept_index(
    product: str = "ubpr_ratio_single", form_type: str | None = None,
    *, section: str | None = None, cycle_ids: str | None = None
) -> dict[str, dict[str, Any]]:
    """Return ``{CODE: {"name", "narrative", "monetary", "is_text"}}`` per concept."""
    from openbb_federal_reserve.utils.cache import cached, seconds_until_next_release

    def _producer() -> dict[str, dict[str, Any]]:
        """Join the product taxonomy types with the MDRM name and definition maps."""
        from openbb_federal_reserve.utils.cdr import fetch_taxonomy, parse_taxonomy
        from openbb_federal_reserve.utils.mdrm import (
            fetch_mdrm_definitions,
            fetch_mdrm_dictionary,
        )

        import zipfile
        from warnings import warn

        try:
            types = {
                concept["mdrm"]: concept["data_type"]
                for concept in parse_taxonomy(fetch_taxonomy(product, form_type))
            }
        except zipfile.BadZipFile:
            if not product.startswith("ubpr_") or section is None:
                raise
            warn("FFIEC taxonomy archive is invalid; using explicit report datatype metadata.", UserWarning, stacklevel=2)
            types = _report_concept_types(section, cycle_ids)
        names = fetch_mdrm_dictionary()
        definitions = fetch_mdrm_definitions()
        return {
            code: {
                "name": clean_name(names.get(code)),
                "narrative": _narrative(definitions.get(code)),
                "monetary": data_type == "Monetary",
                "is_text": data_type == "Text",
            }
            for code, data_type in types.items()
        }

    return cached(
        ("concept_index_report_types_v2", product, form_type or "", section, cycle_ids)
        if section is not None else ("concept_index", product, form_type or ""),
        lambda: seconds_until_next_release("quarterly"),
        _producer,
    )


def numeric_concept_metadata(index: dict, code: str | None) -> dict:
    """Require explicit units before returning any numeric report line.

    A partial reference-bank map is useful only for the codes it resolves.
    Missing codes must never silently inherit the dimensionless default.
    """
    from openbb_core.app.model.abstract.error import OpenBBError

    metadata = index.get(code or "")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("monetary"), bool):
        raise OpenBBError(
            f"FFIEC datatype metadata is unresolved for concept {code or '<missing>'}; "
            "cannot safely scale numeric report values."
        )
    return metadata
