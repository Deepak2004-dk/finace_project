"""
Bank Parser — DEBUG TOOL
========================
Add this router to your FastAPI app temporarily:

    from debug_parser import get_debug_router
    app.include_router(get_debug_router())

Then POST your PDF to:
    POST /statement/debug

It returns a full JSON report showing exactly what pdfplumber extracts,
what headers are detected, and why transactions may be missed.

Also usable as a CLI:
    python debug_parser.py statement.pdf
"""

import re
import json
import tempfile
import os
import pdfplumber
from pathlib import Path


# ── Copy the same header sets from bank_parser so detection is identical ──

DEBIT_HEADERS = {
    "debit", "debits", "dr",
    "debit(rs)", "debit (rs)", "debit(inr)", "debit (inr)",
    "debits(rs)", "debits (rs)", "debits(inr)", "debits (inr)",
    "withdrawal", "withdrawals", "withdrawal (inr)", "withdrawals (inr)",
    "amount debited", "paid out",
}
CREDIT_HEADERS = {
    "credit", "credits", "cr",
    "credit(rs)", "credit (rs)", "credit(inr)", "credit (inr)",
    "credits(rs)", "credits (rs)", "credits(inr)", "credits (inr)",
    "deposit", "deposits", "deposit (inr)", "deposits (inr)",
    "amount credited", "received", "money in",
}
DATE_HEADERS = {
    "date", "date and time", "txn date", "transaction date",
    "value date", "posting date", "date(value date)",
}
DESC_HEADERS = {
    "description", "transaction details", "particulars", "narration",
    "details", "remarks", "payment details", "transaction description",
}
BAL_HEADERS = {
    "balance", "bal", "closing balance", "running balance",
    "balance(rs)", "balance (rs)",
}
REF_HEADERS = {
    "ref no.", "ref no", "reference", "cheque no", "cheque number",
    "ref no./cheque no", "chq no", "utr", "ref/cheque no",
    "ref no./cheque no.", "cheque/reference#", "chq/ref number",
}


def normalize_header(h) -> str:
    if not h:
        return ""
    return re.sub(r"\s+", " ", str(h).strip().lower())


def normalize_header_bare(h) -> str:
    s = normalize_header(h)
    s = re.sub(r"\s*\(.*?\)", "", s).strip()
    return s


def match_any(full, bare, header_set):
    return full in header_set or bare in header_set


def detect_columns(header_row):
    cols = {}
    for i, cell in enumerate(header_row):
        full = normalize_header(cell)
        bare = normalize_header_bare(cell)
        if match_any(full, bare, DATE_HEADERS) and "date" not in cols:
            cols["date"] = i
        elif match_any(full, bare, DESC_HEADERS) and "desc" not in cols:
            cols["desc"] = i
        elif match_any(full, bare, DEBIT_HEADERS) and "debit" not in cols:
            cols["debit"] = i
        elif match_any(full, bare, CREDIT_HEADERS) and "credit" not in cols:
            cols["credit"] = i
        elif match_any(full, bare, BAL_HEADERS) and "balance" not in cols:
            cols["balance"] = i
        elif match_any(full, bare, REF_HEADERS) and "ref" not in cols:
            cols["ref"] = i
    return cols


def is_header_like(row):
    text = " ".join(str(c) for c in row if c).lower()
    return bool(re.search(
        r"\b(date|transaction|debit|credit|withdrawal|deposit|balance|narration|particulars|cheque)\b",
        text
    ))


EXTRACTION_STRATEGIES = [
    {"name": "lines_strict",
     "vertical_strategy": "lines_strict", "horizontal_strategy": "lines_strict",
     "snap_tolerance": 5, "join_tolerance": 3},
    {"name": "lines",
     "vertical_strategy": "lines", "horizontal_strategy": "lines",
     "snap_tolerance": 4, "join_tolerance": 4},
    {"name": "text+lines",
     "vertical_strategy": "text", "horizontal_strategy": "lines",
     "snap_tolerance": 3},
    {"name": "text+text",
     "vertical_strategy": "text", "horizontal_strategy": "text",
     "snap_tolerance": 3},
]


def debug_pdf(pdf_path: str) -> dict:
    report = {
        "file": pdf_path,
        "pages": [],
        "summary": {},
    }

    with pdfplumber.open(pdf_path) as pdf:
        report["summary"]["total_pages"] = len(pdf.pages)

        for page_num, page in enumerate(pdf.pages):
            page_report = {
                "page": page_num + 1,
                "strategies": [],
                "raw_text_snippet": (page.extract_text() or "")[:500],
            }

            best_strategy = None
            best_table_count = 0

            for strat in EXTRACTION_STRATEGIES:
                strat_name = strat.pop("name")
                tables = page.extract_tables(strat)
                strat["name"] = strat_name  # put it back

                tables_info = []
                for t_idx, table in enumerate(tables or []):
                    if not table:
                        continue

                    # Find header row
                    header_row = None
                    header_idx = -1
                    for idx, row in enumerate(table[:5]):
                        if is_header_like(row):
                            header_row = row
                            header_idx = idx
                            break

                    detected_cols = detect_columns(header_row) if header_row else {}

                    tables_info.append({
                        "table_index": t_idx,
                        "row_count": len(table),
                        "col_count": max(len(r) for r in table if r),
                        "header_row_index": header_idx,
                        "header_cells": header_row,
                        "detected_columns": detected_cols,
                        "col_detection_ok": (
                            "date" in detected_cols and
                            ("debit" in detected_cols or "credit" in detected_cols)
                        ),
                        "first_5_data_rows": [
                            [str(c) for c in row]
                            for row in table[header_idx + 1: header_idx + 6]
                        ] if header_idx >= 0 else [
                            [str(c) for c in row]
                            for row in table[:5]
                        ],
                    })

                    if len(tables or []) > best_table_count:
                        best_table_count = len(tables or [])
                        best_strategy = strat_name

                page_report["strategies"].append({
                    "strategy": strat_name,
                    "tables_found": len(tables or []),
                    "tables": tables_info,
                })

            page_report["best_strategy"] = best_strategy
            report["pages"].append(page_report)

    # ── Summary diagnosis ─────────────────────────────────────────
    issues = []
    for p in report["pages"]:
        for s in p["strategies"]:
            for t in s["tables"]:
                if not t["col_detection_ok"]:
                    issues.append(
                        f"Page {p['page']} / {s['strategy']} / table {t['table_index']}: "
                        f"column detection FAILED. "
                        f"Headers seen: {t['header_cells']} → mapped: {t['detected_columns']}"
                    )

    report["summary"]["issues"] = issues if issues else ["None — column detection looks OK"]
    report["summary"]["recommendation"] = (
        "Check 'issues' above. If headers are detected but cols are wrong, "
        "the header text doesn't match any known alias — add it to the appropriate "
        "header set in bank_parser.py. "
        "If NO tables are found at all, the PDF may be image-based (scanned) "
        "and needs OCR via pytesseract."
    )

    return report


# ─────────────────────────────────────────────────────────────────
#  FASTAPI ROUTER
# ─────────────────────────────────────────────────────────────────
def get_debug_router():
    try:
        from fastapi import APIRouter, UploadFile, File, HTTPException

        router = APIRouter()

        @router.post("/statement/debug")
        async def debug_statement(file: UploadFile = File(...)):
            if not file.filename.lower().endswith(".pdf"):
                raise HTTPException(400, "Only PDF files are supported for debug.")

            content = await file.read()
            if not content:
                raise HTTPException(400, "Empty file.")

            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            try:
                tmp.write(content)
                tmp.flush()
                tmp.close()
                result = debug_pdf(tmp.name)
            finally:
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass

            return result

        return router

    except ImportError:
        print("[debug_parser] FastAPI not installed.")
        return None


# ─────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python debug_parser.py <path_to_pdf>")
        sys.exit(1)

    result = debug_pdf(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # ── Print a human-readable summary ───────────────────────────
    print("\n" + "=" * 60)
    print("DIAGNOSIS SUMMARY")
    print("=" * 60)
    for issue in result["summary"]["issues"]:
        print("⚠  ", issue)
    print()
    print("💡 ", result["summary"]["recommendation"])
    print()
    for page in result["pages"]:
        print(f"── Page {page['page']} ──────────────────────────────")
        print(f"   Raw text snippet: {page['raw_text_snippet'][:120]!r}")
        for strat in page["strategies"]:
            if strat["tables_found"] > 0:
                print(f"   [{strat['strategy']}] found {strat['tables_found']} table(s)")
                for t in strat["tables"]:
                    status = "✓ OK" if t["col_detection_ok"] else "✗ FAILED"
                    print(f"     Table {t['table_index']}: {t['row_count']} rows × "
                          f"{t['col_count']} cols | col detection: {status}")
                    print(f"     Headers: {t['header_cells']}")
                    print(f"     Mapped:  {t['detected_columns']}")
                    if t["first_5_data_rows"]:
                        print(f"     First data row: {t['first_5_data_rows'][0]}")