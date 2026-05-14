"""
bank_statement_parser.py  v3.0
================================
Universal Indian Bank Statement Parser
Fixed: Indian Bank table format, IOB narration merging,
ATM WDL date parsing, description truncation

Supports: SBI, Canara Bank (OCR), Kotak Mahindra, IDFC First,
Indian Overseas Bank (IOB), Indian Bank, Slice, Paytm
"""

import re
import sys
import os
import argparse
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
import pdfplumber
import pandas as pd

# ─────────────────────────── DATA MODEL ──────────────────────────────────────

@dataclass
class Transaction:
    date: str = ""
    description: str = ""
    debit: float = 0.0
    credit: float = 0.0
    balance: float = 0.0
    txn_type: str = ""
    category: str = ""
    bank: str = ""
    account_holder: str = ""
    source_file: str = ""

# ─────────────────────────── CATEGORISATION ──────────────────────────────────

CATEGORY_RULES = [
    (r"salary|payroll|ctc|stipend|fellowship|wage|hike|increment|eternal\s*limited", "Salary / Income"),
    (r"zomato|swiggy|food|restaurant|cafe|hotel|biryani|pizza|dine|eat|mess|canteen|tiffin|bakery|tea\s*lion|ambi\s*hotel|mangos|karupatti|avenue\s*food|street\s*of\s*arabia|pizza\s*hut|udankudi|dominos|domino", "Food & Dining"),
    (r"petrol|fuel|diesel|bpcl|hpcl|iocl|petrol\s*bunk|bp\s*petrol|bheru\s*elec", "Fuel & Energy"),
    (r"ola|uber|rapido|metro|bus|train|irctc|railway|flight|airline|cab|auto|paytm\s*travel", "Transport"),
    (r"netflix|prime|spotify|hotstar|zee5|youtube|movie|cinema|pvr|inox|game|steam|apple\s*media", "Entertainment"),
    (r"apollo|pharmeasy|1mg|medplus|pharmacy|hospital|clinic|doctor|lab|diagnostic|medicine|health", "Healthcare"),
    (r"airtel|jio|bsnl|\bvi\b|vodafone|tata\s*sky|dth|recharge|mobile\s*bill|broadband|internet|google\s*india\s*digital", "Mobile & Internet"),
    (r"rent|electricity|water\s*bill|gas\s*bill|maintenance|society|flat|landlord|sms.chg|amc.chg|atm.amc", "Rent & Utilities"),
    (r"amazon|flipkart|myntra|meesho|nykaa|ajio|store|mart|supermarket|grocer|big\s*bazaar|cotton\s*house|ecom.uni|unipinindia|ecom-uni", "Shopping"),
    (r"emi|loan|finance|lendingkart|mpokket|krazybee|navi\s*lim|l.?t\s*fin|bajaj\s*fin|nach|ecs|samukh|l\s*and\s*t", "Loan / EMI"),
    (r"sip|mutual\s*fund|zerodha|groww|upstox|invest|nse|bse|share|stock|demat|\bfd\b|fixed\s*deposit|\brd\b|recurring", "Investment"),
    (r"insurance|lic|policy|premium|irdai", "Insurance"),
    (r"school|college|university|course|tuition|exam\s*fee|jeppiaar|library|exam\s*cell", "Education"),
    (r"atm.wdl|atm.wd|atm\s*withdrawal|atm_amc|atl/|atm.nfs|atm.cash|cash\s*withdrawal|cash\s*deposit|cdm|tran\s*date.*atm|bna.*chennai|bnasemmancherry", "Cash / ATM"),
    (r"interest\s*cr|interest\s*credit|savings\s*interest|monthly\s*savings|int\.pd|credit\s*interest", "Interest Income"),
    (r"npci\s*cr|post\s*matri|festival\s*allow|festival\s*allowance", "Income / Receipts"),
    (r"neft|rtgs|imps|fund\s*transfer|self\s*transfer|ift/|bank\s*transfer", "Bank Transfer"),
    (r"tax|gst|tds|income\s*tax|it\s*dept|government|govt", "Tax / Government"),
    (r"refund|cashback|reward|bonus|rebate", "Refund / Cashback"),
    (r"google\s*pay|gpay|phonepe|paytm\b|bhim|upi", "UPI Payment"),
    (r"slice|mobiler", "Loan / EMI"),
]

DATE_PAT = re.compile(
    r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"
    r"|\d{1,2}\s+[A-Za-z]{3}\s+\d{2,4}"
    r"|\d{1,2}\s+[A-Za-z]{3}\s+'?\d{2}"
    r"|\d{1,2}-[A-Za-z]{3}-\d{2,4}"
    r"|\d{4}-\d{2}-\d{2})\b"
)

MONS = dict(jan="01",feb="02",mar="03",apr="04",may="05",jun="06",
    jul="07",aug="08",sep="09",oct="10",nov="11",dec="12")

AMOUNT_PAT = re.compile(r"[\d,]+\.\d{2}")

# ─────────────────────────── HELPER FUNCTIONS ─────────────────────────────────

def categorise(text: str) -> str:
    t = text.lower()
    for pattern, category in CATEGORY_RULES:
        if re.search(pattern, t):
            return category
    return "Others"

def parse_amount(text) -> float:
    if not text or str(text).strip() in ("-", "", "Nil", "nil", "N/A", "None", "nan"):
        return 0.0
    cleaned = re.sub(r"[₹,\s]", "", str(text))
    cleaned = re.sub(r"(?i)(cr|dr)\s*$", "", cleaned).strip()
    cleaned = re.sub(r"^INR\s*", "", cleaned, flags=re.IGNORECASE)
    try:
        return abs(float(cleaned))
    except ValueError:
        return 0.0

def detect_type(row_text: str, debit: float, credit: float) -> str:
    if credit > 0 and debit == 0:
        return "CREDIT"
    if debit > 0 and credit == 0:
        return "DEBIT"
    u = row_text.upper()
    if re.search(r"UPI/CR\b|DEP\s*TFR|SALARY|NEFT.*CR|IMPS.*CR|IFT.*CR|INTEREST\s*CR|NPCI\s*CR|\bCR\b|\bCREDIT\b|DEPOSIT|RECEIVED", u):
        return "CREDIT"
    if re.search(r"UPI/DR\b|WDL\s*TFR|NACH|ECS|ATM|ATL/|\bDR\b|\bDEBIT\b|WITHDRAW|PAYMENT\b", u):
        return "DEBIT"
    return "UNKNOWN"

def norm_date(raw: str) -> str:
    raw = raw.strip().split("\n")[0]
    for pat, fmt in [
        (r"(\d{1,2})\s+([A-Za-z]{3})\s+'(\d{2})", "apos"),
        (r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{2,4})", "mon"),
        (r"(\d{1,2})-([A-Za-z]{3})-(\d{2,4})", "mon"),
        (r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", "dmy"),
        (r"(\d{4})-(\d{2})-(\d{2})", "iso"),
    ]:
        m = re.match(pat, raw)
        if not m:
            continue
        a, b, c = m.groups()
        if fmt == "apos":
            return f"20{c}-{MONS.get(b.lower(),'00')}-{a.zfill(2)}"
        if fmt == "mon":
            y = f"20{c}" if len(c) == 2 else c
            return f"{y}-{MONS.get(b.lower(),'00')}-{a.zfill(2)}"
        if fmt == "dmy":
            y = f"20{c}" if len(c) == 2 else c
            return f"{y}-{b.zfill(2)}-{a.zfill(2)}"
        if fmt == "iso":
            return f"{a}-{b}-{c}"
    return raw

def detect_bank(text: str, fname: str) -> str:
    t, f = text[:3000].lower(), fname.lower()
    if "paytm" in f:
        return "Paytm UPI"
    if "slice" in f:
        return "Slice (Small Finance Bank)"
    if "canara" in t or "canara" in f:
        return "Canara Bank"
    if "kotak" in f or "kotak mahindra" in t:
        return "Kotak Mahindra Bank"
    if "idfc first" in t or "idfb" in t or "idfb0" in t:
        return "IDFC First Bank"
    if "indian overseas" in t or "iob" in f:
        return "Indian Overseas Bank"
    if "indian bank" in t or "idib000" in t or "idib" in f:
        return "Indian Bank"
    if "state bank" in t or "sbin" in t:
        return "SBI"
    if "slice" in t:
        return "Slice (Small Finance Bank)"
    if "paytm" in t:
        return "Paytm UPI"
    return "Unknown Bank"

def extract_holder(text: str) -> str:
    patterns = [
        r"(?:account\s*holder\s*name|customer\s*name)\s*[:\-]?\s*([A-Z][A-Za-z\s\.]{2,35})",
        r"^(T\s+PRAGADEESH|T\s+Pragadeesh|Prithvirajan\s*\.|REJU\s+V|R\s*K\s+Jeevaprasad|Deepak\s+K)",
        r"mr\.?\s+([A-Z][A-Za-z\s\.]{2,30})\b",
    ]
    for p in patterns:
        m = re.search(p, text, re.I | re.M)
        if m:
            n = m.group(1).strip()
            if len(n) > 2 and not re.search(r"account|branch|email|phone|statement|details|savings|currency", n, re.I):
                return n[:40]
    return ""

# ─────────────────────────── TABLE PARSER ───────────────────────────────────

def _col_index(header: list[str], patterns: list[str]) -> int:
    """Find first column index matching any of the given regex patterns."""
    for i, h in enumerate(header):
        for p in patterns:
            if re.search(p, h, re.I):
                return i
    return -1

def parse_table(table: list, bank: str) -> list[Transaction]:
    txns = []
    if not table or len(table) < 2:
        return txns

    raw_header = table[0]
    header = [re.sub(r"\s+", " ", str(h or "")).lower().strip() for h in raw_header]

    col_date    = _col_index(header, [r"\bdate\b"])
    col_debit   = _col_index(header, [r"debit|withdrawal|dr\.?\b"])
    col_credit  = _col_index(header, [r"credit|deposit|cr\.?\b"])
    col_balance = _col_index(header, [r"balance|bal\b"])
    col_desc    = _col_index(header, [r"desc|narrat|particular|detail|transact"])

    if col_date == -1 and len(header) >= 5:
        col_date = 0; col_desc = 1; col_debit = 2; col_credit = 3; col_balance = 4

    if col_date == -1 and len(header) >= 7:
        col_date = 1; col_desc = 2; col_debit = 4; col_credit = 5; col_balance = 6

    if col_date == -1:
        col_date = 0
    if col_desc == -1:
        col_desc = 2 if len(header) > 2 else 1

    for row in table[1:]:
        if not row or all((not c or str(c).strip() in ("", "None")) for c in row):
            continue

        rc = [re.sub(r"\s+", " ", str(c or "")).strip() for c in row]

        raw_date = rc[col_date] if col_date < len(rc) else ""
        raw_date = raw_date.split("\n")[0].strip()

        if not DATE_PAT.search(raw_date):
            dm = DATE_PAT.search(" ".join(rc[:3]))
            if dm:
                raw_date = dm.group(1)
            else:
                continue

        if col_desc < len(rc):
            desc_raw = rc[col_desc]
        else:
            desc_raw = " ".join(rc[1:3])

        desc_raw = re.sub(r"\(\d{1,2}-[A-Za-z]{3}-\d{4}\)", "", desc_raw)
        desc = re.sub(r"\s+", " ", desc_raw).strip()[:160]

        def ga(c):
            return parse_amount(rc[c]) if c != -1 and c < len(rc) else 0.0

        debit   = ga(col_debit)
        credit  = ga(col_credit)
        balance = ga(col_balance)

        row_text = " ".join(rc)
        txn_type = detect_type(row_text, debit, credit)

        if debit == 0 and credit == 0:
            continue

        txns.append(Transaction(
            date=norm_date(raw_date),
            description=desc,
            debit=debit,
            credit=credit,
            balance=balance,
            txn_type=txn_type,
            category=categorise(desc + " " + row_text),
        ))

    return txns

# ─────────────────────────── TEXT FALLBACK ─────────────────────────────────

SKIP_RE = re.compile(
    r"^(opening balance|closing balance|total debit|total credit|balance b/?f|"
    r"brought forward|carry forward|summary|statement|page\s*\d|nil|n/a|"
    r"date|particulars|narration|description|please|note:|never share|this is|---)", re.I
)

def parse_line(line: str) -> Optional[Transaction]:
    m = DATE_PAT.search(line)
    if not m:
        return None
    amounts = AMOUNT_PAT.findall(line)
    if not amounts:
        return None
    floats = [parse_amount(a) for a in amounts]
    u = line.upper()
    has_cr = bool(re.search(r"UPI/CR|DEP\s*TFR|\bCR\b|\bCREDIT\b|DEPOSIT|SALARY|NEFT.*CR|IFT.*CR|INTEREST\s*CR|NPCI\s*CR", u))
    has_dr = bool(re.search(r"UPI/DR|WDL\s*TFR|\bDR\b|\bDEBIT\b|WITHDRAW|NACH|ECS|ATM|ATL/|PAYMENT", u))
    debit = credit = balance = 0.0
    if len(floats) == 1:
        amt = floats[0]
        if has_cr and not has_dr:
            credit = amt
        else:
            debit = amt
    elif len(floats) == 2:
        balance = floats[-1]
        amt = floats[0]
        if has_cr and not has_dr:
            credit = amt
        else:
            debit = amt
    else:
        balance = floats[-1]
        if has_cr and not has_dr:
            credit = floats[0]
        elif has_dr and not has_cr:
            debit = floats[0]
        else:
            debit, credit = floats[0], floats[1]

    fa = line.find(amounts[0])
    fe = m.end()
    desc = re.sub(r"\s+", " ", line[fe:fa] if fa > fe else line[fe:]).strip()[:160]
    txn_type = detect_type(line, debit, credit)
    return Transaction(
        date=norm_date(m.group(1)), description=desc,
        debit=debit, credit=credit, balance=balance,
        txn_type=txn_type, category=categorise(desc + " " + line),
    )

def parse_text_lines(text: str) -> list[Transaction]:
    txns = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    i = 0
    while i < len(lines):
        line = lines[i]
        if SKIP_RE.match(line):
            i += 1
            continue
        if i + 1 < len(lines) and not DATE_PAT.search(lines[i+1][:25]):
            line = line + " " + lines[i+1]
            i += 1
        t = parse_line(line)
        if t and (t.debit > 0 or t.credit > 0):
            txns.append(t)
        i += 1
    return txns

# ─────────────────────────── OCR ───────────────────────────────────────────

def ocr_pdf(pdf_path: str) -> str:
    try:
        from pdf2image import convert_from_path
        import pytesseract
        print("  ⚙ Running OCR (scanned/image PDF)…")
        imgs = convert_from_path(pdf_path, dpi=200)
        return "\n".join(pytesseract.image_to_string(img, config="--psm 6") for img in imgs)
    except Exception as e:
        print(f"  ⚠ OCR failed: {e}")
        return ""

# ─────────────────────────── SLICE PARSER ─────────────────────────────────

def parse_slice(text: str) -> list[Transaction]:
    txns = []
    pat = re.compile(
        r"(\d{2}\s+[A-Za-z]{3}\s+'?\d{2})\s+"
        r"(.+?)\s+"
        r"\d{13,}\s+"
        r"([+\-]₹[\d,]+(?:\.\d{2})?)\s+"
        r"(₹[\d,]+(?:\.\d{2})?)",
        re.DOTALL,
    )
    for m in pat.finditer(text):
        date_raw, desc, amt_str, bal_str = m.groups()
        sign  = -1 if amt_str.startswith("-") else 1
        amt   = parse_amount(re.sub(r"[+\-₹,]", "", amt_str))
        bal   = parse_amount(re.sub(r"[₹,]", "", bal_str))
        debit = amt if sign == -1 else 0.0
        cred  = amt if sign ==  1 else 0.0
        desc  = re.sub(r"\s+", " ", desc).strip()[:160]
        txns.append(Transaction(
            date=norm_date(date_raw), description=desc,
            debit=debit, credit=cred, balance=bal,
            txn_type="DEBIT" if debit > 0 else "CREDIT",
            category=categorise(desc),
        ))
    if len(txns) < 3:
        txns = parse_text_lines(text)
    return txns

# ─────────────────────────── PAYTM PARSER ─────────────────────────────────

def parse_paytm(text: str) -> list[Transaction]:
    txns = []
    for m in re.finditer(r"([+\-]\s*Rs\.[\d,]+(?:\.\d{2})?)", text):
        amt_str = re.sub(r"\s", "", m.group(1))
        sign    = -1 if amt_str.startswith("-") else 1
        amt     = parse_amount(re.sub(r"[+\-Rs\.₹,]", "", amt_str))
        debit   = amt if sign == -1 else 0.0
        cred    = amt if sign ==  1 else 0.0
        ctx     = text[max(0, m.start()-200):m.start()]
        dm      = DATE_PAT.search(ctx)
        date_raw = norm_date(dm.group(1)) if dm else "2026-02-01"
        desc    = re.sub(r"\s+", " ", ctx[-160:]).strip()
        txns.append(Transaction(
            date=date_raw, description=desc,
            debit=debit, credit=cred, balance=0.0,
            txn_type="DEBIT" if debit > 0 else "CREDIT",
            category=categorise(desc),
        ))
    return txns

# ─────────────────────────── IOB PARSER ────────────────────────────────────

IOB_COLS = dict(date=0, desc=1, ref=2, txn_type=3, debit=4, credit=5, balance=6)

def parse_iob_row(row: list) -> Optional[Transaction]:
    if not row or len(row) < 6:
        return None
    rc = [re.sub(r"\s+", " ", str(c or "")).strip() for c in row]

    raw_date = rc[IOB_COLS["date"]]
    raw_date = re.sub(r"\(.*?\)", "", raw_date).strip()
    if not DATE_PAT.search(raw_date):
        return None

    desc_raw = rc[IOB_COLS["desc"]]
    desc = re.sub(r"\s+", " ", desc_raw).strip()[:160]
    if not desc or desc.lower() in ("none", "-"):
        return None

    if re.search(r"^(total|effective|opening|closing|brought|carry)", desc, re.I):
        return None

    debit_raw  = rc[IOB_COLS["debit"]]  if IOB_COLS["debit"]  < len(rc) else "-"
    credit_raw = rc[IOB_COLS["credit"]] if IOB_COLS["credit"] < len(rc) else "-"
    bal_raw    = rc[IOB_COLS["balance"]]if IOB_COLS["balance"] < len(rc) else ""

    debit  = parse_amount(debit_raw)  if debit_raw.strip()  not in ("-","","None") else 0.0
    credit = parse_amount(credit_raw) if credit_raw.strip() not in ("-","","None") else 0.0
    bal    = parse_amount(bal_raw)

    if debit == 0 and credit == 0:
        return None

    txn_type = "CREDIT" if credit > 0 and debit == 0 else "DEBIT"

    return Transaction(
        date=norm_date(raw_date),
        description=desc,
        debit=debit, credit=credit, balance=bal,
        txn_type=txn_type,
        category=categorise(desc),
    )

def parse_iob_pdf(pdf_path: str) -> list[Transaction]:
    txns = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or []
            for table in tables:
                if not table:
                    continue

                first = table[0] if table else []
                first_str = " ".join(str(c or "").lower() for c in first)
                if re.search(r"date.*value|particulars|debit.*credit", first_str):
                    data_rows = table[1:]
                else:
                    data_rows = table

                for row in data_rows:
                    if not row or all(str(c or "").strip() in ("","None","-") for c in row):
                        continue
                    row_str = " ".join(str(c or "") for c in row)
                    if re.search(r"^\s*\d{1,3},\d{2,3},\d{3}\.\d{2}", row_str):
                        continue
                    t = parse_iob_row(row)
                    if t:
                        txns.append(t)

    return txns

# ─────────────────────────── MAIN PARSER ───────────────────────────────────

def parse_pdf(pdf_path: str) -> list[Transaction]:
    path = Path(pdf_path)
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"

    bank   = detect_bank(full_text, path.stem)
    holder = extract_holder(full_text)

    if len(full_text.strip()) < 100:
        full_text = ocr_pdf(pdf_path)
        bank      = detect_bank(full_text, path.stem)
        holder    = extract_holder(full_text)

    print(f"  Bank          : {bank}")
    print(f"  Holder        : {holder or '(not found)'}")

    all_txns: list[Transaction] = []

    if "Paytm" in bank:
        all_txns = parse_paytm(full_text)
    elif "Slice" in bank:
        all_txns = parse_slice(full_text)
    elif "IDFC First" in bank:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    all_txns.extend(parse_table(table, bank))
        if len(all_txns) < 2:
            all_txns = parse_text_lines(full_text)
    elif "Indian Bank" in bank:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    all_txns.extend(parse_table(table, bank))
        if len(all_txns) < 2:
            all_txns = parse_text_lines(full_text)
    elif "Indian Overseas" in bank:
        all_txns = parse_iob_pdf(pdf_path)
        if len(all_txns) < 2:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    for table in (page.extract_tables() or []):
                        all_txns.extend(parse_table(table, bank))
    else:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    all_txns.extend(parse_table(table, bank))
        if len(all_txns) < 2:
            all_txns = parse_text_lines(full_text)

    # Deduplicate
    seen: dict = {}
    unique = []
    for t in all_txns:
        k = (t.date, t.description[:60], round(t.debit, 2), round(t.credit, 2))
        count = seen.get(k, 0)
        seen[k] = count + 1
        if count == 0:
            unique.append(t)

    # Filter junk
    SKIP_DESC = re.compile(
        r"^(opening balance|closing balance|total|brought forward|carry forward|"
        r"nil|n/a|\-+)$", re.I
    )
    clean = []
    for t in unique:
        if t.debit == 0 and t.credit == 0:
            continue
        if SKIP_DESC.match(t.description.strip()):
            continue
        if len(t.description.strip()) < 2:
            continue
        t.bank = bank
        t.account_holder = holder
        t.source_file = path.name
        clean.append(t)

    print(f"  Transactions  : {len(clean)}")
    return clean

# ─────────────────────────── SUMMARY ────────────────────────────────────────

def print_summary(txns: list[Transaction]):
    if not txns:
        print("\n  ⚠ No transactions found.")
        return
    df = pd.DataFrame([asdict(t) for t in txns])
    tc = df["credit"].sum()
    td = df["debit"].sum()
    net = tc - td
    print("\n" + "═"*62)
    print("  CONSOLIDATED SUMMARY")
    print("═"*62)
    print(f"  Total transactions : {len(df)}")
    print(f"  Credits (income)   : ₹{tc:>14,.2f}")
    print(f"  Debits (expenses)  : ₹{td:>14,.2f}")
    print(f"  Net flow           : ₹{net:>14,.2f}  ({'surplus' if net>=0 else 'deficit'})")
    print()
    print("  Spending by category (top 12):")
    cat = df[df["debit"]>0].groupby("category")["debit"].sum().sort_values(ascending=False).head(12)
    for c, a in cat.items():
        bar = "█" * min(int(a/max(cat.max(),1)*20), 20)
        print(f"    {c:<32} ₹{a:>10,.2f}  {bar}")
    print()
    print("  By bank:")
    for b, g in df.groupby("bank"):
        print(f"    {b:<40} {len(g):>4} txns  CR ₹{g['credit'].sum():>10,.0f}  DR ₹{g['debit'].sum():>10,.0f}")
    print("═"*62)

# ─────────────────────────── EXCEL EXPORT ───────────────────────────────────

def export_excel(txns: list[Transaction], out: str):
    df = pd.DataFrame([asdict(t) for t in txns])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df.sort_values(["source_file", "date"], inplace=True)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d").fillna("")
    cols = ["date","bank","account_holder","txn_type","category",
            "debit","credit","balance","description","source_file"]
    dfo = df[[c for c in cols if c in df.columns]]
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        dfo.to_excel(w, sheet_name="All Transactions", index=False)
        for bank, g in dfo.groupby("bank"):
            g.to_excel(w, sheet_name=re.sub(r"[^\w ]","",bank)[:28], index=False)
        
        rows = []
        for bank, g in dfo.groupby("bank"):
            rows.append({
                "Bank": bank,
                "Account Holder": g["account_holder"].iloc[0],
                "Transactions": len(g),
                "Total Credits (₹)": round(g["credit"].sum(), 2),
                "Total Debits (₹)": round(g["debit"].sum(), 2),
                "Net (₹)": round(g["credit"].sum()-g["debit"].sum(), 2),
            })
        pd.DataFrame(rows).to_excel(w, sheet_name="Summary", index=False)
        
        cat = dfo.groupby("category").agg(
            Transactions=("credit","count"),
            Total_Credit=("credit","sum"),
            Total_Debit=("debit","sum"),
        ).reset_index().sort_values("Total_Debit", ascending=False)
        cat.to_excel(w, sheet_name="By Category", index=False)
        
        df2 = pd.DataFrame([asdict(t) for t in txns])
        df2["date"] = pd.to_datetime(df2["date"], errors="coerce")
        df2["month"] = df2["date"].dt.to_period("M").astype(str)
        m = df2.groupby("month").agg(
            Transactions=("credit","count"),
            Total_Credit=("credit","sum"),
            Total_Debit=("debit","sum"),
        ).reset_index()
        m.to_excel(w, sheet_name="Monthly Trend", index=False)
        print(f"\n  ✅ Excel saved → {out}")

# ─────────────────────────── CLI ────────────────────────────────────────────

def collect_pdfs(inputs):
    import glob as _g
    pdfs = []
    for inp in inputs:
        p = Path(inp)
        if p.is_dir():
            pdfs.extend(str(f) for f in p.glob("**/*.pdf"))
        elif p.suffix.lower() == ".pdf" and p.exists():
            pdfs.append(str(p))
        else:
            pdfs.extend(_g.glob(inp))
    return sorted(set(pdfs))

def main():
    ap = argparse.ArgumentParser(description="Universal Indian Bank Statement Parser v3.0")
    ap.add_argument("inputs", nargs="+", help="PDF file(s), glob, or folder")
    ap.add_argument("--output", "-o", default="parsed_statements.xlsx")
    ap.add_argument("--json",    action="store_true")
    ap.add_argument("--no-excel", action="store_true")
    args = ap.parse_args()
    pdfs = collect_pdfs(args.inputs)
    if not pdfs:
        print("❌ No PDFs found.")
        sys.exit(1)
    print(f"\n🔍 Parsing {len(pdfs)} PDF(s)…")
    all_txns = []
    for pdf in pdfs:
        print(f"\n📄 {Path(pdf).name}")
        try:
            all_txns.extend(parse_pdf(pdf))
        except Exception as e:
            print(f"  ⚠ Error: {e}")
    print_summary(all_txns)
    if not args.no_excel and all_txns:
        export_excel(all_txns, args.output)
    if args.json and all_txns:
        jp = args.output.replace(".xlsx", ".json")
        with open(jp, "w") as f:
            json.dump([asdict(t) for t in all_txns], f, indent=2, default=str)
            print(f"  📄 JSON → {jp}")

if __name__ == "__main__":
    main()

# ─────────────────────────── FASTAPI INTEGRATION ────────────────────────────

def parse_bank_pdf_to_finace_format(pdf_path: str) -> dict:
    """
    Parse a bank PDF and return in Finace dashboard format:
        { transactions, total_income, total_expense, transaction_count }
        Each transaction: { date, desc, amount (signed), raw_amount, type, cat, page }
    """
    raw_txns = parse_pdf(pdf_path)
    transactions = []
    for t in raw_txns:
        is_credit = t.txn_type == "CREDIT"
        transactions.append({
            "date":       t.date,
            "desc":       t.description,
            "amount":     round(t.credit if is_credit else -t.debit, 2),
            "raw_amount": round(t.credit if is_credit else t.debit, 2),
            "type":       "Credit" if is_credit else "Debit",
            "cat":        t.category,
            "page":       1,
        })
    total_income  = round(sum(t["raw_amount"] for t in transactions if t["amount"] > 0), 2)
    total_expense = round(sum(t["raw_amount"] for t in transactions if t["amount"] < 0), 2)
    return {
        "transactions":      transactions,
        "total_income":      total_income,
        "total_expense":     total_expense,
        "transaction_count": len(transactions),
        "pages_processed":   len(transactions),
    }

def get_fastapi_router():
    """Return a FastAPI router with bank statement parsing endpoints."""
    try:
        from fastapi import APIRouter, File, UploadFile, Form, HTTPException
        import tempfile

        router = APIRouter()

        @router.post("/statement/parse-ocr")
        async def parse_ocr(file: UploadFile = File(...)):
            if not file.filename.lower().endswith(".pdf"):
                raise HTTPException(400, "Only PDF files are supported")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(await file.read())
                tmp_path = tmp.name
            try:
                result = parse_bank_pdf_to_finace_format(tmp_path)
                if not result["transactions"]:
                    raise HTTPException(422, "No transactions found in this PDF.")
                return result
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(500, f"Parse error: {str(e)}")
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        @router.post("/statement/parse-text")
        async def parse_text_ep(text: str = Form(...)):
            if not text or len(text.strip()) < 10:
                raise HTTPException(400, "No text provided.")
            txns = parse_text_lines(text.strip())
            if not txns:
                raise HTTPException(422, "No transactions found in pasted text.")
            transactions = []
            for t in txns:
                is_credit = t.txn_type == "CREDIT"
                transactions.append({
                    "date":       t.date,
                    "desc":       t.description,
                    "amount":     round(t.credit if is_credit else -t.debit, 2),
                    "raw_amount": round(t.credit if is_credit else t.debit, 2),
                    "type":       "Credit" if is_credit else "Debit",
                    "cat":        t.category,
                    "page":       1,
                })
            total_income  = round(sum(t["raw_amount"] for t in transactions if t["amount"] > 0), 2)
            total_expense = round(sum(t["raw_amount"] for t in transactions if t["amount"] < 0), 2)
            return {
                "transactions":      transactions,
                "total_income":      total_income,
                "total_expense":     total_expense,
                "transaction_count": len(transactions),
                "pages_processed":   1,
            }

        return router
    except ImportError:
        return None
