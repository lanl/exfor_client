#!/usr/bin/env python3
"""
EXFOR Web API Python client

Features
- Search datasets by Target/Reaction/Quantity and other filters (uses x4list)
- Download dataset data in CSV (computational/universal), C4, or C5(+covariance) (uses x4get)
- Optional one-step search+download for many datasets (uses x4dat)
- Parse CSV to pandas DataFrame (if pandas installed) or list of dicts
- Preserve uncertainties (per-point) as provided by EXFOR

References
- Web-API docs: https://nds.iaea.org/exfor/x4guide/API/
- Examples tested in this client come from the official API examples

Note
- Be courteous: avoid hammering the server; use small concurrency and timeouts
- Always keep dataset provenance (DatasetID, accession/Subentry) in your outputs
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import requests
except Exception as e:
    requests = None  # type: ignore

try:
    import pandas as pd  # type: ignore
except Exception:
    pd = None  # optional

BASE = "https://nds.iaea.org/exfor"
HEADERS = {
    "User-Agent": "EXFOR-API-Python/1.0 (+https://nds.iaea.org/exfor/x4guide/API/)",
    "Accept": "*/*",
}
TIMEOUT = 30


class HttpError(RuntimeError):
    pass


def _check_requests():
    if requests is None:
        raise RuntimeError(
            "The 'requests' package is required. Install with: pip install requests"
        )


def _get(url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:  # type: ignore
    _check_requests()
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200:
                return r
            # On Cloudflare/transient errors, small backoff
            time.sleep(1 + attempt)
        except requests.RequestException:
            time.sleep(1 + attempt)
    raise HttpError(f"GET failed: {url} params={params}")


# ----------------------------
# Search: x4list
# ----------------------------

def search_datasets(
    target: Optional[str] = None,
    reaction: Optional[str] = None,
    quantity: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    output: str = "json",
) -> Dict[str, Any]:
    """
    Query EXFOR for a list of datasets matching criteria.

    Parameters
    - target, reaction, quantity: strings as per EXFOR codes (e.g., target='PB-204', reaction='n,g', quantity='SIG')
    - extra: any additional filters, e.g., {'Author1': 'Michel', 'Accnum': '23114'}
    - output: 'json' | 'xml' | 'csv' | 'txt'

    Returns JSON object for output='json'; for other formats, returns a dict with 'raw' key holding text.
    """
    params: Dict[str, Any] = {}
    if target:
        params["Target"] = target
    if reaction:
        params["Reaction"] = reaction
    if quantity:
        params["Quantity"] = quantity
    if extra:
        params.update(extra)

    # Select output flag
    if output.lower() == "json":
        params["json"] = ""
    elif output.lower() == "xml":
        params["xml"] = ""
    elif output.lower() == "csv":
        params["csv"] = ""
    elif output.lower() == "txt":
        params["txt"] = ""
    else:
        raise ValueError("output must be one of: json, xml, csv, txt")

    url = f"{BASE}/x4list"
    r = _get(url, params=params)

    if output.lower() == "json":
        return r.json()
    else:
        return {"raw": r.text}


# ----------------------------
# Download individual dataset: x4get
# ----------------------------

def download_dataset_csv(
    dataset_id: str,
    plus: int = 1,
) -> Tuple[List[Dict[str, Any]], Optional["pd.DataFrame"]]:
    """
    Download a dataset in CSV and parse it.

    Parameters
    - dataset_id: EXFOR DatasetID (as given by x4list JSON 'id' or by EXFOR docs)
    - plus: 1 => computational CSV; 2 => universal CSV with labeled axes

    Returns (records, dataframe)
    - records: list of dicts (always returned)
    - dataframe: pandas DataFrame if pandas is installed; otherwise None

    Notes
    - In computational CSV (plus=1), typical columns include:
        DATA (units), DATA-ERR, EN (EV), EN-RSL-FW (EV), ...
    - In universal CSV (plus=2), typical columns include:
        y:Value, y, dy, x2:IncEn, x2(eV), dx2(eV), ...
    - Keep statistical/systematic components distinct when present (ERR-S, ERR-SYS)
    """
    params = {"DatasetID": dataset_id, "op": "csv", "plus": str(plus)}
    url = f"{BASE}/x4get"
    r = _get(url, params=params)
    text = r.text

    # Parse CSV text
    buf = io.StringIO(text)
    reader = csv.DictReader(buf)
    rows: List[Dict[str, Any]] = []
    for row in reader:
        # Convert numeric-looking fields where safe
        parsed: Dict[str, Any] = {}
        for k, v in row.items():
            if v is None or v == "" or v.lower() == "null":
                parsed[k] = None
                continue
            # Try float
            try:
                parsed[k] = float(v)
            except Exception:
                parsed[k] = v
        rows.append(parsed)

    df = None
    if pd is not None:
        try:
            df = pd.DataFrame(rows)
        except Exception:
            df = None

    return rows, df


def download_dataset_c4(dataset_id: str) -> str:
    """Download a dataset as C4 text (not parsed)."""
    params = {"DatasetID": dataset_id, "op": "c4"}
    url = f"{BASE}/x4get"
    r = _get(url, params=params)
    return r.text


def download_dataset_c5(
    dataset_id: str, op: str = "c5"
) -> str:
    """
    Download a dataset in C5 family:
      - op='c5'   : C5 format
      - op='c5a'  : C5 auto-renormalized
      - op='c5m'  : C5 with generated correlation matrix
      - op='c5ma' : C5 auto-renormalized with correlation matrix

    Returns raw text.
    """
    if op not in {"c5", "c5a", "c5m", "c5ma"}:
        raise ValueError("op must be one of: c5, c5a, c5m, c5ma")
    params = {"DatasetID": dataset_id, "op": op}
    url = f"{BASE}/x4get"
    r = _get(url, params=params)
    return r.text


# ----------------------------
# One-step retrieval for many datasets: x4dat
# ----------------------------

def bulk_download(
    target: Optional[str] = None,
    reaction: Optional[str] = None,
    quantity: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    op: str = "c4",
) -> str:
    """
    One-step retrieval: find datasets by criteria and get data in one file (C4 or C5* family).

    Parameters
    - op: 'c4', 'c5', 'c5a', 'c5m', or 'c5ma'

    Returns raw text of the combined output.
    """
    if op not in {"c4", "c5", "c5a", "c5m", "c5ma"}:
        raise ValueError("op must be one of: c4, c5, c5a, c5m, c5ma")

    params: Dict[str, Any] = {}
    if target:
        params["Target"] = target
    if reaction:
        params["Reaction"] = reaction
    if quantity:
        params["Quantity"] = quantity
    if extra:
        params.update(extra)

    params["op"] = op

    url = f"{BASE}/x4dat"
    r = _get(url, params=params)
    return r.text


# ----------------------------
# Entry/Subentry retrieval: x4get (sub)
# ----------------------------

def get_entry_or_subentry(sub: str, plus: Optional[int] = None) -> str:
    """
    Retrieve an Entry or Subentry.
    - sub like 'A1495' (Entry) or 'A1495003' (Subentry). Historical version with ':YYYYMMDD'.
    - plus=6 => CSV for Subentry; plus=5 => X5 JSON; leave None for raw EXFOR format.
    Returns raw text (or JSON string if plus=5).
    """
    params: Dict[str, Any] = {"sub": sub}
    if plus is not None:
        params["plus"] = str(plus)
    url = f"{BASE}/x4get"
    r = _get(url, params=params)
    return r.text


# ----------------------------
# Helpers to extract common numeric columns from CSV
# ----------------------------

def extract_xy_from_csv_rows(rows: List[Dict[str, Any]]) -> Tuple[List[float], List[float], List[Optional[float]]]:
    """
    Heuristic extractor for (energy_eV, value, uncertainty) from CSV rows produced by x4get&op=csv.

    This tries common headers for energies and values:
    - Energy: prefer 'EN (EV) 1.1' (plus=1) or 'x2(eV)' (plus=2)
    - Value: prefer 'DATA (B) 0.1' (plus=1) or 'y'/'y:Value' (plus=2)
    - Uncertainty: prefer 'DATA-ERR (B) 0.911' (plus=1) or 'dy' (plus=2)

    Returns lists: energies_eV, values, uncertainties (None if missing)
    """
    if not rows:
        return [], [], []

    # Candidate keys by priority
    energy_keys = [
        "EN (EV) 1.1",  # plus=1 example
        "x2(eV)",       # plus=2 example for Incident Energy
        "EN(EV)",       # sometimes without space
        "x1(eV)",       # rare
    ]
    value_keys = [
        "DATA (B) 0.1",
        "y",            # plus=2 actual numeric value
        "y:Value",      # label column sometimes used to describe units
        "Data(B)",
        "DATA(B)",
    ]
    err_keys = [
        "DATA-ERR (B) 0.911",
        "ERR-T",
        "ERR-S",
        "ERR-SYS",
        "dy",
    ]

    # Determine keys present
    present_keys = set().union(*[set(r.keys()) for r in rows])
    ek = next((k for k in energy_keys if k in present_keys), None)
    vk = next((k for k in value_keys if k in present_keys), None)
    dk = next((k for k in err_keys if k in present_keys), None)

    if ek is None or vk is None:
        # Fallback: try to find columns with 'EN(' and 'DATA'
        for k in present_keys:
            if ek is None and k.upper().startswith("EN") and "EV" in k.upper():
                ek = k
            if vk is None and (k.upper().startswith("DATA") or k == "y"):
                vk = k
        # If still None, raise
        if ek is None or vk is None:
            raise ValueError(f"Could not find energy/value columns in CSV headers: {sorted(present_keys)}")

    E: List[float] = []
    Y: List[float] = []
    DY: List[Optional[float]] = []
    for r in rows:
        e = r.get(ek)
        y = r.get(vk)
        de = r.get(dk) if dk else None
        # Filter non-numeric
        if isinstance(e, (int, float)) and isinstance(y, (int, float)):
            E.append(float(e))
            Y.append(float(y))
            DY.append(float(de) if isinstance(de, (int, float)) else None)
    return E, Y, DY


# ----------------------------
# CLI
# ----------------------------

def _cmd_search(args: argparse.Namespace) -> None:
    extra = {}
    for kv in args.extra or []:
        if "=" not in kv:
            raise SystemExit(f"--extra must be key=value, got: {kv}")
        k, v = kv.split("=", 1)
        extra[k] = v
    data = search_datasets(
        target=args.target, reaction=args.reaction, quantity=args.quantity, extra=extra, output=args.output
    )
    if args.output == "json":
        print(json.dumps(data, indent=2))
    else:
        sys.stdout.write(data["raw"])  # type: ignore


def _cmd_download(args: argparse.Namespace) -> None:
    if args.format == "csv":
        rows, df = download_dataset_csv(args.dataset, plus=args.plus)
        # Save CSV exactly as returned if outfile endswith .csv
        if args.out:
            # Fetch raw to preserve exact server formatting
            params = {"DatasetID": args.dataset, "op": "csv", "plus": str(args.plus)}
            r = _get(f"{BASE}/x4get", params=params)
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(r.text)
            print(f"Saved CSV to {args.out} ({len(rows)} rows)")
        else:
            # Print preview
            print(f"Parsed {len(rows)} rows. Columns: {list(rows[0].keys()) if rows else []}")
            # Try extract XY
            try:
                E, Y, DY = extract_xy_from_csv_rows(rows)
                print(f"Extracted {len(E)} points: E(eV)[0:5]={E[:5]} Y[0:5]={Y[:5]} DY[0:5]={DY[:5]}")
            except Exception as e:
                print(f"Note: {e}")
    elif args.format in {"c4", "c5", "c5a", "c5m", "c5ma"}:
        if args.format == "c4":
            text = download_dataset_c4(args.dataset)
        else:
            text = download_dataset_c5(args.dataset, op=args.format)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"Saved {args.format.upper()} to {args.out} (chars={len(text)})")
        else:
            sys.stdout.write(text)
    else:
        raise SystemExit("Unsupported format. Use csv, c4, c5, c5a, c5m, or c5ma")


def _cmd_bulk(args: argparse.Namespace) -> None:
    extra = {}
    for kv in args.extra or []:
        if "=" not in kv:
            raise SystemExit(f"--extra must be key=value, got: {kv}")
        k, v = kv.split("=", 1)
        extra[k] = v
    text = bulk_download(
        target=args.target,
        reaction=args.reaction,
        quantity=args.quantity,
        extra=extra,
        op=args.op,
    )
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Saved bulk {args.op} to {args.out} (chars={len(text)})")
    else:
        sys.stdout.write(text)


def _cmd_entry(args: argparse.Namespace) -> None:
    text = get_entry_or_subentry(args.sub, plus=args.plus)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Saved to {args.out} (chars={len(text)})")
    else:
        sys.stdout.write(text)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="EXFOR Web API client")
    sub = p.add_subparsers(dest="cmd", required=True)

    # search
    ps = sub.add_parser("search", help="Search datasets (x4list)")
    ps.add_argument("--target", help="Target, e.g., PB-204 or PB-*", default=None)
    ps.add_argument("--reaction", help="Reaction, e.g., n,g or n,*", default=None)
    ps.add_argument("--quantity", help="Quantity, e.g., SIG, DA, DE, NU, FY", default=None)
    ps.add_argument("--output", choices=["json", "xml", "csv", "txt"], default="json")
    ps.add_argument("--extra", nargs="*", help="Additional filters key=value (e.g., Author1=Michel Accnum=23114)")
    ps.set_defaults(func=_cmd_search)

    # download single dataset
    pdn = sub.add_parser("download", help="Download one dataset (x4get)")
    pdn.add_argument("--dataset", required=True, help="EXFOR DatasetID")
    pdn.add_argument("--format", default="csv", help="csv|c4|c5|c5a|c5m|c5ma")
    pdn.add_argument("--plus", type=int, default=1, help="CSV mode: 1=computational, 2=universal")
    pdn.add_argument("--out", help="Output filepath (if omitted, prints to stdout or summary)")
    pdn.set_defaults(func=_cmd_download)

    # bulk one-step retrieval
    pb = sub.add_parser("bulk", help="One-step retrieval across many datasets (x4dat)")
    pb.add_argument("--target", default=None)
    pb.add_argument("--reaction", default=None)
    pb.add_argument("--quantity", default=None)
    pb.add_argument("--op", default="c4", help="c4|c5|c5a|c5m|c5ma")
    pb.add_argument("--extra", nargs="*", help="Additional filters key=value")
    pb.add_argument("--out", help="Output filepath (if omitted, prints to stdout)")
    pb.set_defaults(func=_cmd_bulk)

    # entry/subentry retrieval
    pe = sub.add_parser("entry", help="Retrieve Entry/Subentry (x4get?sub=...)")
    pe.add_argument("--sub", required=True, help="Entry (A1495) / Subentry (A1495003) or with :YYYYMMDD")
    pe.add_argument("--plus", type=int, help="Optional plus mode (e.g., 5 for X5 JSON, 6 for CSV)")
    pe.add_argument("--out", help="Output filepath")
    pe.set_defaults(func=_cmd_entry)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except HttpError as e:
        print(f"HTTP error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


# ----------------------------
# C5M: covariance and metadata parsing
# ----------------------------

def download_dataset_c5m(dataset_id: str) -> str:
    """Download a dataset in C5M format (with generated covariance and rich metadata)."""
    params = {"DatasetID": dataset_id, "op": "c5m"}
    url = f"{BASE}/x4get"
    r = _get(url, params=params)
    return r.text


def _parse_c5m_metadata(c5m_text: str) -> dict:
    """Parse key experimental metadata fields from C5M header lines.
    Returns a dict with fields like TITLE, AUTHORS, AUTHOR1, YEAR, REFERENCE1, INSTITUTE, METHOD, REACTION, MF, MT, TARGET, etc.
    """
    meta = {}
    lines = c5m_text.splitlines()
    # Simple key-value extraction from lines starting with '#KEY'
    keys = {
        "TITLE", "AUTHORS", "AUTHOR1", "YEAR", "REFERENCE1", "X4REF1",
        "INSTITUTE", "METHOD", "REACTION", "MF", "MT", "TARGET", "PROJ", "PRODUCT",
    }
    current_key = None
    for ln in lines:
        if not ln.startswith("#"):
            continue
        # Normalize continuation '#+'
        if ln.startswith("#+") and current_key and current_key in meta:
            meta[current_key] = (meta[current_key] + " " + ln[2:].strip()).strip()
            continue
        # Parse '#KEY   value'
        s = ln[1:].strip()
        if not s:
            continue
        parts = s.split(None, 1)
        if len(parts) == 1:
            key = parts[0].strip()
            val = ""
        else:
            key, val = parts[0].strip(), parts[1].strip()
        if key in keys:
            meta[key] = val
            current_key = key
        else:
            current_key = None
    return meta


def _parse_c5m_covariance(c5m_text: str) -> dict:
    """Extract covariance information from a C5M text.
    Returns dict with arrays: E_min, E_max, data, std_pct, sigma, corr (NxN), cov (NxN).
    """
    lines = c5m_text.splitlines()
    # Locate COVARDATA block
    i0 = None
    i1 = None
    for i, ln in enumerate(lines):
        if ln.startswith("#COVARDATA"):
            i0 = i
        if ln.startswith("#/COVARDATA"):
            i1 = i
            break
    if i0 is None or i1 is None or i1 <= i0:
        return {}
    data_rows = []
    # After '#COVARDATA' there is a header line, then data lines until '#/COVARDATA'
    for ln in lines[i0+1:i1]:
        if not ln.strip() or ln.startswith("#"):
            continue
        # Tokenize by whitespace
        toks = ln.strip().split()
        # Expect at least 4 columns, then a variable number of correlations
        if len(toks) < 4:
            continue
        try:
            e_min = float(toks[0])
            e_max = float(toks[1])
            y = float(toks[2])
            std_pct = float(toks[3])
        except Exception:
            continue
        corr_vals = []
        for t in toks[4:]:
            try:
                corr_vals.append(float(t))
            except Exception:
                pass
        data_rows.append({
            "E_min": e_min,
            "E_max": e_max,
            "y": y,
            "std_pct": std_pct,
            "corr_list": corr_vals,
        })
    n = len(data_rows)
    if n == 0:
        return {}
    # Build correlation matrix (percent -> fraction)
    corr = [[0.0]*n for _ in range(n)]
    for i in range(n):
        # fill diagonal default 1.0 if not provided
        corr[i][i] = 1.0
    for i, row in enumerate(data_rows):
        vals = row["corr_list"]
        # The format typically lists lower triangular including diag: length i+1
        for j, v in enumerate(vals):
            jj = j  # assumes order: corr with rows 0..i
            if jj < 0 or jj > i:
                continue
            rho = float(v)/100.0
            corr[i][jj] = rho
            corr[jj][i] = rho
    # Standard deviations from percent of data
    y = [r["y"] for r in data_rows]
    std_pct = [r["std_pct"] for r in data_rows]
    sigma = [(sp/100.0)*yy for sp, yy in zip(std_pct, y)]
    # Covariance matrix
    cov = [[0.0]*n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            cov[i][j] = corr[i][j] * sigma[i] * sigma[j]
    return {
        "E_min": [r["E_min"] for r in data_rows],
        "E_max": [r["E_max"] for r in data_rows],
        "data": y,
        "std_pct": std_pct,
        "sigma": sigma,
        "corr": corr,
        "cov": cov,
    }


def get_dataset_covariance_and_metadata(dataset_id: str) -> dict:
    """Convenience: fetch C5M for dataset and return a dict with:
      - raw_c5m: raw text
      - metadata: dict of experimental metadata
      - covariance: dict with E_min, E_max, data, std_pct, sigma, corr, cov (if available)
    """
    text = download_dataset_c5m(dataset_id)
    meta = _parse_c5m_metadata(text)
    covar = _parse_c5m_covariance(text)
    return {"raw_c5m": text, "metadata": meta, "covariance": covar}


if __name__ == "__main__":
    raise SystemExit(main())
