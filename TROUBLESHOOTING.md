# Bank Statement Parser - Troubleshooting Guide

## Error: "No transactions found"

### What This Means
The parser is running but not finding any transactions in the PDF. This can happen for several reasons:

## Debugging Steps

### Step 1: Check the Server Logs
When you upload a PDF, check the **terminal where the backend is running**. You should see debug messages like:

```
[bank_parser] Opening PDF: /tmp/...
[bank_parser] Processing page 1/1
[bank_parser] Found 1 table(s) on page 1
[bank_parser] Processing table 0 with 10 rows
[bank_parser] Found header at row 0: ...
[bank_parser] Detected columns: {'date': 0, 'desc': 1, 'debit': 2, 'credit': 3, 'balance': 4}
[bank_parser] Merged 8 rows to 8 data rows
[bank_parser] Processed 5 rows, skipped 3
```

**Read these messages carefully** to understand where the process is failing.

### Step 2: Common Issues and Solutions

#### A) **"Found 0 table(s) on page X"**
**Problem:** The parser cannot extract any tables from the PDF  
**Solutions:**
1. Check if the PDF is actually a document/image or if it's corrupted
2. Try uploading a different bank statement to confirm it's not a PDF-specific issue
3. The PDF may be scanned as an image - if so, you'll need OCR (which requires pytesseract and Tesseract software)

#### B) **"No header found, using saved schema" OR "Header missing date or debit/credit columns"**
**Problem:** The parser found a table but can't identify the header row  
**Solutions:**
1. Ensure the PDF has a clear header row with:
   - A "Date" column (or "Transaction Date" / "Date and Time")
   - A "Debit" and/or "Credit" column (or "Withdrawals" / "Deposits")
2. The header must be in the first few rows (within first 5 rows)

#### C) **"Found 1 table ... Processed 0 rows, skipped X"**
**Problem:** Found a table with header, but no transactions were extracted  
**Solutions:**
1. **Check if amounts are being parsed:**
   - The debit/credit columns must have valid amounts
   - Supported formats: `1,000.00` / `INR 1000` / `+1000` / `-1000`

2. **Check if dates are being recognized:**
   - Supported date formats:
     - `01 Feb, 2026` or `01 Feb 2026` or `01-Feb-2026`
     - `01/02/2026` or `01-02-2026`
     - `2026-02-01`

3. **Check description column:**
   - The description/particulars column must have text
   - It can't be empty or just "-"

### Step 3: Manual Testing

#### Option A: Test via Terminal
```bash
cd "c:\Users\acer\ai-vs-finace\ai-financial-chatbot -code3 cursor"
python -c "from backend.bank_parser import parse_bank_pdf; import json; result = parse_bank_pdf('path/to/your/statement.pdf'); print(json.dumps(result, indent=2))"
```

This will show you exactly what the parser found.

#### Option B: Test via Text Upload
Instead of uploading a PDF, try the **Parse Text** feature and paste a few lines of your statement in this format:

```
Date              Details                          Debits         Credits        Balance
01 Feb, 2026      OPENING BALANCE                  -              -              0.00
05 Feb, 2026      UPI Transfer                     9,000.00       -              9,000.00
08 Feb, 2026      ATM Withdrawal                   -              6,500.00       2,500.00
```

This helps determine if the issue is with PDF parsing or transaction detection logic.

## What the Parser Supports

### Bank Formats
✅ Yes Bank  
✅ Axis Bank  
✅ Canara Bank  
✅ IOB Bank  
✅ Federal Bank  
✅ KVB Bank  
✅ SBI Bank  
✅ HDFC Bank  
✅ Flexible/wrapped layouts  

### Column Variations
The following column names are recognized (case-insensitive):

| Column Type | Accepted Names |
|------------|----------------|
| **Date** | Date, Txn Date, Transaction Date, Value Date, Posting Date |
| **Description** | Transaction Details, Description, Particulars, Narration, Details |
| **Debit** | Debit, Debits, Withdrawal(s), Debit(Rs), Debit(INR) |
| **Credit** | Credit, Credits, Deposit(s), Credit(Rs), Credit(INR) |
| **Balance** | Balance, Bal, Closing Balance, Running Balance |

### Amount Formats
✅ `1,23,456.78` (Indian format)  
✅ `INR 1000.00` (with currency prefix)  
✅ `+5000.00` or `-5000.00` (signed amounts)  
✅ `1000 CR` or `1000 DR` (CR/DR suffixes)  

### Date Formats
✅ `01 Feb, 2026`  
✅ `01-Feb-2026` or `01 Feb 2026`  
✅ `2026-02-01` (ISO format)  
✅ `01/02/2026` or `01-02-2026` (DD/MM/YYYY)  

## Advanced: Enable Debug Mode

Edit `backend/bank_parser.py` and you can add more detailed logging by checking the print statements already in the code. The debug output is shown in your terminal when the server is running.

## Still Not Working?

If none of the above works, please:

1. **Check the terminal output** carefully - copy-paste the entire debug log
2. **Verify the PDF is not**:
   - Corrupted or incomplete
   - A scanned image (requires OCR setup)
   - Password-protected
   - Using unusual/custom table formats

3. **Try with a different bank statement** from the same bank to see if it's a format issue

4. **Last resort**: Use the "Parse Text" feature by copying the transaction lines directly from the PDF
