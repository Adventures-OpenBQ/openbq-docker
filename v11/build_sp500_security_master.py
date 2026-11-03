# SPDX-License-Identifier: Apache-2.0
"""Build a local, real-data Security Master bootstrap from retained source bytes.

No provider credentials or network are used here. This is a current observed
snapshot, not historical membership or an installed TemporalDB publication.
"""

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import sys
from uuid import NAMESPACE_URL, uuid5
from urllib.parse import urlsplit, parse_qs

VERSION = "sp500-bootstrap-1"


def validate_source_metadata(source):
    url = urlsplit(source["url"])
    forbidden = {"api_token", "token", "password", "api_key", "authorization"}
    keys = {key.lower() for key in parse_qs(url.query)} | {
        key.lower() for key in source.get("parameters", {})
    }
    if url.username or url.password or keys & forbidden:
        raise ValueError("credential-bearing source metadata is forbidden")


def identity(kind, key):
    return str(
        uuid5(NAMESPACE_URL, "urn:openbq:security-master:v1:" + kind + ":" + key)
    )


def valid_isin(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value
    ):
        return False
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in value)
    return (
        sum(
            (n * 2 // 10 + n * 2 % 10) if i % 2 else n
            for i, n in enumerate(map(int, reversed(digits)))
        )
        % 10
        == 0
    )


class ConstituentsTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.cell = False
        self.rows = []
        self.row = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == "table" and dict(attrs).get("id") == "constituents":
            self.active = True
        if self.active and tag == "tr":
            self.row = []
        if self.active and tag in ("td", "th"):
            self.cell = True
            self.text = []

    def handle_data(self, text):
        if self.active and self.cell:
            self.text.append(text)

    def handle_endtag(self, tag):
        if not self.active:
            return
        if tag in ("td", "th") and self.cell:
            self.row.append(" ".join("".join(self.text).split()))
            self.cell = False
        if tag == "tr" and self.row:
            self.rows.append(self.row)
        if tag == "table":
            self.active = False


def normalize(components, symbols, wiki, general=None, sec=None):
    general = general or {}
    sec = sec or {}
    tables = {
        name: []
        for name in [
            "issuers",
            "securities",
            "listings",
            "identifiers",
            "classifications",
            "memberships",
            "issues",
        ]
    }
    refs = {}
    for row in symbols:
        refs.setdefault(row["Code"], []).append(row)
    words = {row[0]: row for row in wiki}
    if len(words) != len(wiki):
        raise ValueError("ambiguous Wikipedia ticker")
    seen = set()
    securities = set()
    issuers = set()

    def issue(symbol, code, detail):
        tables["issues"].append(dict(symbol=symbol, code=code, detail=detail))

    for member in sorted(components, key=lambda r: r["Code"]):
        symbol = member["Code"]
        if member.get("Exchange") != "US":
            raise ValueError("non-US constituent needs an explicit provider mapping")
        if symbol in seen:
            raise ValueError("duplicate index constituent")
        seen.add(symbol)
        candidates = refs.get(symbol, [])
        if len(candidates) > 1:
            raise ValueError("ambiguous listing reference: " + symbol)
        listing = candidates[0] if candidates else {}
        if not listing:
            issue(
                symbol,
                "MISSING_LISTING_REFERENCE",
                "Constituent retained without fabricated listing fields",
            )
        alias = {"BRK-B": "BRK.B", "BF-B": "BF.B"}.get(symbol, symbol)
        w = words.get(symbol) or words.get(alias)
        if w is None:
            issue(
                symbol,
                "MISSING_CIK_CLASSIFICATION",
                "No matching reported Wikipedia identity",
            )
        wiki_cik = (
            w[6].zfill(10)
            if w and re.fullmatch(r"\d{1,10}", w[6]) and int(w[6]) > 0
            else None
        )
        g = general.get(symbol, {})
        general_code = str(g.get("Code") or symbol)
        if general_code not in {symbol, alias}:
            issue(
                symbol,
                "GENERAL_SYMBOL_MISMATCH",
                "General response identified " + general_code + "; enrichment withheld",
            )
            g = {}
        raw_cik = str(g.get("CIK") or "")
        provider_cik = (
            raw_cik.zfill(10)
            if re.fullmatch(r"\d{1,10}", raw_cik) and int(raw_cik) > 0
            else None
        )
        confirmed = []
        for candidate in dict.fromkeys([wiki_cik, provider_cik]):
            evidence = sec.get(candidate, {})
            evidence_cik = str(evidence.get("cik") or "").zfill(10)
            if (
                candidate
                and evidence_cik == candidate
                and {symbol, alias}.intersection(evidence.get("tickers") or [])
            ):
                confirmed.append(candidate)
        if len(confirmed) > 1:
            raise ValueError("conflicting SEC ticker evidence: " + symbol)
        cik = confirmed[0] if confirmed else provider_cik or wiki_cik
        verified = bool(confirmed)
        cik_source = (
            "sec-" + cik
            if verified
            else "general-" + symbol
            if provider_cik
            else "wikipedia"
        )
        if provider_cik and wiki_cik and provider_cik != wiki_cik:
            issue(
                symbol,
                "CIK_RECONCILED_WITH_SEC" if verified else "CIK_CONFLICT",
                "Provider CIK "
                + provider_cik
                + "; Wikipedia CIK "
                + wiki_cik
                + "; selected "
                + str(cik)
                + (
                    " from SEC ticker evidence"
                    if verified
                    else "; unverified provider precedence"
                ),
            )
        issuer_id = identity("issuer-cik", cik) if cik else None
        if issuer_id and issuer_id not in issuers:
            issuers.add(issuer_id)
            tables["issuers"].append(
                dict(
                    issuer_id=issuer_id,
                    cik=cik,
                    reported_name=(sec[cik].get("name") if verified else None)
                    or g.get("Name")
                    or member["Name"],
                    verification="SEC_ticker_match"
                    if verified
                    else "reported_unverified",
                    source_ref=cik_source,
                )
            )
            tables["identifiers"].append(
                dict(
                    entity_type="issuer",
                    entity_id=issuer_id,
                    scheme="CIK",
                    value=cik,
                    source_ref=cik_source,
                )
            )
        reported_isin = listing.get("Isin") or None
        isin = reported_isin if valid_isin(reported_isin) else None
        if reported_isin and not isin:
            issue(
                symbol,
                "INVALID_ISIN",
                "Reported ISIN failed format/check digit validation",
            )
        security_id = (
            identity("security-isin", isin)
            if isin
            else identity("security-bootstrap", symbol + ".US")
        )
        if security_id in securities:
            raise ValueError(
                "two constituent symbols resolve to one security; review required"
            )
        securities.add(security_id)
        tables["securities"].append(
            dict(
                security_id=security_id,
                issuer_id=issuer_id,
                symbol=symbol,
                name=member["Name"],
                isin=isin,
                isin_reported=reported_isin,
                figi=g.get("OpenFigi") or None,
                cusip=g.get("CUSIP") or None,
                identity_basis="ISIN" if isin else "provisional_provider_symbol",
                source_ref="symbols",
            )
        )
        if isin:
            tables["identifiers"].append(
                dict(
                    entity_type="security",
                    entity_id=security_id,
                    scheme="ISIN",
                    value=isin,
                    source_ref="symbols",
                )
            )
        if g.get("OpenFigi"):
            tables["identifiers"].append(
                dict(
                    entity_type="security",
                    entity_id=security_id,
                    scheme="FIGI_reported",
                    value=g["OpenFigi"],
                    source_ref="general-" + symbol,
                )
            )
        venue = listing.get("Exchange")
        mic = {"NYSE": "XNYS", "NASDAQ": "XNAS"}.get(venue)
        if venue and not mic:
            issue(
                symbol,
                "MIC_REQUIRES_REVIEW",
                "Source venue "
                + venue
                + " and General OperatingMIC "
                + str(g.get("OperatingMIC"))
                + " retained separately; no automatic canonical MIC",
            )
        listing_id = identity("listing", security_id + ":" + str(venue))
        tables["listings"].append(
            dict(
                listing_id=listing_id,
                security_id=security_id,
                provider_symbol=symbol + ".US",
                venue=venue,
                mic=mic,
                reported_operating_mic=g.get("OperatingMIC"),
                currency=listing.get("Currency"),
                country=listing.get("Country"),
                instrument_type=listing.get("Type"),
                source_ref="symbols",
            )
        )
        tables["identifiers"].append(
            dict(
                entity_type="listing",
                entity_id=listing_id,
                scheme="EODHD",
                value=symbol + ".US",
                source_ref="index",
            )
        )
        if w:
            tables["identifiers"].append(
                dict(
                    entity_type="listing",
                    entity_id=listing_id,
                    scheme="Wikipedia_ticker",
                    value=w[0],
                    source_ref="wikipedia",
                )
            )
        for taxonomy, level, value, ref in [
            ("eodhd", "sector", member.get("Sector"), "index"),
            ("eodhd", "industry", member.get("Industry"), "index"),
            ("GICS_reported_by_Wikipedia", "sector", w[2] if w else None, "wikipedia"),
            (
                "GICS_reported_by_Wikipedia",
                "sub_industry",
                w[3] if w else None,
                "wikipedia",
            ),
        ]:
            if value:
                tables["classifications"].append(
                    dict(
                        security_id=security_id,
                        taxonomy=taxonomy,
                        level=level,
                        value=value,
                        effective_from=None,
                        source_ref=ref,
                    )
                )
        for level, key in [
            ("sector", "GicSector"),
            ("industry_group", "GicGroup"),
            ("industry", "GicIndustry"),
            ("sub_industry", "GicSubIndustry"),
        ]:
            value = g.get(key)
            if value and value not in {"N/A", "NA"}:
                tables["classifications"].append(
                    dict(
                        security_id=security_id,
                        taxonomy="GICS_reported_by_EODHD",
                        level=level,
                        value=value,
                        effective_from=None,
                        source_ref="general-" + symbol,
                    )
                )
        weight = str(member["Weight"]) if member.get("Weight") is not None else None
        if weight is not None and not Decimal(0) <= Decimal(weight) <= Decimal(1):
            raise ValueError("invalid index weight")
        tables["memberships"].append(
            dict(
                index_id="GSPC.INDX",
                security_id=security_id,
                listing_id=listing_id,
                weight_fraction=weight,
                effective_from=None,
                effective_to=None,
                status="current_reported",
                reported_added_date=w[5] if w else None,
                source_ref="index",
            )
        )
    return tables


def build(sources_root, output):
    import duckdb

    source_root = Path(sources_root).resolve()
    out = Path(output)
    manifest = json.loads((source_root / "manifest.json").read_text())
    bodies = {}
    sources = []
    for source in manifest["sources"]:
        validate_source_metadata(source)
        path = (source_root / source["path"]).resolve()
        if path.parent != source_root or source["name"] in bodies:
            raise ValueError("invalid source manifest")
        raw = path.read_bytes()
        if source["http_status"] != 200 or sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("unverified source bytes")
        bodies[source["name"]] = raw
        sources.append(
            dict(
                capture_id=identity(
                    "capture", source["sha256"] + source["received_at"]
                ),
                source_name=source["name"],
                url=source["url"],
                parameters_json=json.dumps(
                    source.get("parameters", {}), sort_keys=True
                ),
                received_at=source["received_at"],
                payload_sha256=source["sha256"],
                bytes=str(len(raw)),
                path="sources/" + source["path"],
            )
        )
    for name in ("index", "symbols", "wikipedia"):
        if name not in bodies:
            raise ValueError("missing source " + name)
    index = json.loads(bodies["index"], parse_float=Decimal)
    if index.get("General", {}).get("Code") != "GSPC":
        raise ValueError("source is not the S&P500 index")
    components = list(index["Components"].values())
    parser = ConstituentsTable()
    parser.feed(bodies["wikipedia"].decode())
    expected = [
        "Symbol",
        "Security",
        "GICS Sector",
        "GICS Sub-Industry",
        "Headquarters Location",
        "Date added",
        "CIK",
        "Founded",
    ]
    if not parser.rows or parser.rows[0] != expected:
        raise ValueError("Wikipedia source table changed")
    generals = {
        name.removeprefix("general-"): json.loads(raw)
        for name, raw in bodies.items()
        if name.startswith("general-")
    }
    tables = normalize(
        components,
        json.loads(bodies["symbols"]),
        parser.rows[1:],
        generals,
        {
            name.removeprefix("sec-"): json.loads(raw)
            for name, raw in bodies.items()
            if name.startswith("sec-")
        },
    )
    if not 490 <= len(components) <= 550:
        raise ValueError("unexpected S&P500 constituent count; review source")
    out.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source_root, out / "sources")
    db = duckdb.connect(str(out / "security-master.duckdb"))
    definitions = {
        "issuers": "issuer_id VARCHAR PRIMARY KEY,cik VARCHAR,reported_name VARCHAR,verification VARCHAR,source_ref VARCHAR",
        "securities": "security_id VARCHAR PRIMARY KEY,issuer_id VARCHAR REFERENCES issuers(issuer_id),symbol VARCHAR UNIQUE,name VARCHAR,isin VARCHAR,isin_reported VARCHAR,figi VARCHAR,cusip VARCHAR,identity_basis VARCHAR,source_ref VARCHAR",
        "listings": "listing_id VARCHAR PRIMARY KEY,security_id VARCHAR REFERENCES securities(security_id),provider_symbol VARCHAR UNIQUE,venue VARCHAR,mic VARCHAR,reported_operating_mic VARCHAR,currency VARCHAR,country VARCHAR,instrument_type VARCHAR,source_ref VARCHAR",
        "identifiers": "entity_type VARCHAR,entity_id VARCHAR,scheme VARCHAR,value VARCHAR,source_ref VARCHAR",
        "classifications": "security_id VARCHAR REFERENCES securities(security_id),taxonomy VARCHAR,level VARCHAR,value VARCHAR,effective_from TIMESTAMPTZ,source_ref VARCHAR",
        "memberships": "index_id VARCHAR,security_id VARCHAR REFERENCES securities(security_id),listing_id VARCHAR REFERENCES listings(listing_id),weight_fraction DECIMAL(28,18),effective_from TIMESTAMPTZ,effective_to TIMESTAMPTZ,status VARCHAR,reported_added_date VARCHAR,source_ref VARCHAR",
        "issues": "symbol VARCHAR,code VARCHAR,detail VARCHAR",
        "source_captures": "capture_id VARCHAR PRIMARY KEY,source_name VARCHAR UNIQUE,url VARCHAR,parameters_json VARCHAR,received_at TIMESTAMPTZ,payload_sha256 VARCHAR,bytes BIGINT,path VARCHAR",
    }
    tables["source_captures"] = sources
    for name, definition in definitions.items():
        db.execute("CREATE TABLE " + name + " (" + definition + ")")
        for row in tables[name]:
            db.execute(
                "INSERT INTO " + name + " VALUES (" + ",".join("?" for _ in row) + ")",
                list(row.values()),
            )
    db.execute("""CREATE VIEW security_master AS SELECT s.security_id,s.issuer_id,l.listing_id,s.symbol,l.provider_symbol,s.name,
   i.cik,i.verification AS cik_verification,i.source_ref AS cik_source_ref,s.isin,s.figi,s.cusip,l.venue,l.mic,l.reported_operating_mic,l.currency,l.country,l.instrument_type,
   (SELECT c.value FROM classifications c WHERE c.security_id=s.security_id AND taxonomy='eodhd' AND level='sector') AS provider_sector,
   (SELECT c.value FROM classifications c WHERE c.security_id=s.security_id AND taxonomy='eodhd' AND level='industry') AS provider_industry,
   (SELECT c.value FROM classifications c WHERE c.security_id=s.security_id AND taxonomy='GICS_reported_by_Wikipedia' AND level='sector') AS gics_sector_reported,
   (SELECT c.value FROM classifications c WHERE c.security_id=s.security_id AND taxonomy='GICS_reported_by_EODHD' AND level='sector') AS gics_sector_eodhd,
   (SELECT c.value FROM classifications c WHERE c.security_id=s.security_id AND taxonomy='GICS_reported_by_EODHD' AND level='sub_industry') AS gics_sub_industry_eodhd,
   (SELECT c.value FROM classifications c WHERE c.security_id=s.security_id AND taxonomy='GICS_reported_by_Wikipedia' AND level='sub_industry') AS gics_sub_industry_reported,
   m.index_id,m.weight_fraction,m.status AS membership_status,m.effective_from,m.reported_added_date,
   sc.capture_id AS membership_capture_id,sc.received_at AS membership_observed_at,s.identity_basis
   FROM securities s JOIN listings l USING(security_id) LEFT JOIN issuers i USING(issuer_id)
   JOIN memberships m ON m.security_id=s.security_id AND m.listing_id=l.listing_id
   JOIN source_captures sc ON sc.source_name=m.source_ref""")
    for extension in ("csv", "parquet"):
        target = str((out / ("security-master." + extension)).resolve())
        db.execute(
            "COPY (SELECT * FROM security_master ORDER BY symbol) TO ? (FORMAT "
            + ("CSV, HEADER" if extension == "csv" else "PARQUET")
            + ")",
            [target],
        )
    coverage_values = db.execute(
        "SELECT COUNT(isin),COUNT(cik),COUNT(mic),COUNT(figi),COUNT(cusip) FROM security_master"
    ).fetchone()
    report = {
        "runtime": {"python": sys.version.split()[0], "duckdb": duckdb.__version__},
        "builder_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "format": VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "index": "GSPC.INDX",
        "counts": {name: len(rows) for name, rows in tables.items()},
        "coverage": dict(
            zip(["isin", "cik", "canonical_mic", "figi", "cusip"], coverage_values)
        ),
        "weight_sum": str(
            db.execute("SELECT SUM(weight_fraction) FROM memberships").fetchone()[0]
        ),
        "weight_policy": "source fractions retained exactly; not renormalized",
        "issues": tables["issues"],
        "sources": sources,
        "limits": [
            "current observed membership, not point-in-time historical membership",
            "CIK uses retained SEC submissions when the CIK and ticker match; otherwise reported provider/Wikipedia evidence; GICS sources remain separate",
            "issuer names are representative security names, not verified legal entity names",
            "security/listing IDs are internal surrogates anchored to reported ISIN/venue, not external authority identifiers",
            "not yet an installed Security Master API or TemporalDB accepted publication",
        ],
    }
    schema = {
        name: [
            {"column": row[0], "type": row[1], "nullable": row[2], "key": row[3]}
            for row in db.execute("DESCRIBE " + name).fetchall()
        ]
        for name in [*definitions, "security_master"]
    }
    db.close()
    (out / "schema.json").write_text(json.dumps(schema, indent=2) + "\n")
    (out / "build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    (
        out / "queries.sql"
    ).write_text("""-- Current observed universe, not historical membership.
SELECT COUNT(*) AS securities, COUNT(DISTINCT issuer_id) AS reported_issuers FROM security_master;
SELECT symbol, name, isin, cik, venue, mic, gics_sector_reported FROM security_master ORDER BY symbol;
SELECT gics_sector_reported, COUNT(*) AS securities FROM security_master GROUP BY 1 ORDER BY 1;
SELECT * FROM issues;
SELECT source_name, received_at, payload_sha256 FROM source_captures ORDER BY source_name;
""")
    readme = f"""# S&P 500 Security Master — current observed snapshot

Built from real retrieved EODHD index/listing reference responses, with
Wikipedia-reported CIK and GICS enrichment. This snapshot contains
{report["counts"]["securities"]} securities and {report["counts"]["issuers"]}
reported issuer CIK groups. It is a queryable local bootstrap, not yet a deployed
Security Master API or accepted TemporalDB publication.

Open `security-master.duckdb` read-only with DuckDB. `security_master` is the
joined view; normalized tables retain issuers, securities, listings, identifiers,
classifications, memberships, source captures and quality issues. See
`queries.sql`, `schema.json`, and `build-report.json`. The CSV and Parquet contain
the same joined dataset. Source bodies and retrieval metadata are in `sources/`;
`checksums.json` covers the output bytes. API tokens are not included.

Effective membership start dates are unknown. Wikipedia's date-added is a
separate reported attribute, not a verified historical membership interval.
CIK uses SEC submissions only when both CIK and ticker match; otherwise it remains reported and unverified. Conflicting reported values are retained in issues. GICS is not authority verified. Provider taxonomy
is separate from reported GICS. Null identifiers are unknown, not fabricated.
Issuer names are representative security names, not verified legal entity names.
Internal UUIDs are surrogates, not authoritative external IDs.

Source weights total {report["weight_sum"]} as a fraction; they are not
renormalized. Inspect `issues` for withheld or conflicting fields. ISIN format
and check digits are validated; that alone is not identity-authority validation.
FIGI coverage: {report["coverage"]["figi"]}; CUSIP coverage: {report["coverage"]["cusip"]}.

When available, `sources/access-checks.json` records which endpoints actually
accepted the configured key. ETF access does not establish bulk or historical
ETF holdings access. No subscription is changed by this offline builder.
"""
    (out / "README.md").write_text(readme)
    (out / "build-script.py").write_bytes(Path(__file__).read_bytes())
    files = {
        str(p.relative_to(out)): sha256(p.read_bytes()).hexdigest()
        for p in sorted(out.rglob("*"))
        if p.is_file()
    }
    (out / "checksums.json").write_text(json.dumps(files, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.sources, args.output)
    print(
        json.dumps(
            {k: report[k] for k in ["counts", "coverage", "weight_sum", "issues"]}
        )
    )
