# Bank Statement Parser v5 Enhancements

## Overview
The bank statement parser has been significantly enhanced to recognize and process multiple flexible table formats beyond the well-structured standard formats. Now handles wrapped text, variable spacing, and flexible layouts commonly found in various bank statement PDF exports.

## Key Improvements

### 1. **Additional Table Extraction Strategies** (7 total)
   - `lines_strict`: Fully bordered tables (SBI, HDFC, Yes Bank)
   - `lines`: Semi-bordered tables (Canara, ICICI)
   - `text+lines`: Horizontal lines only (Axis Bank, some flexible)
   - `text+text`: Fully borderless (Federal Bank, KVB)
   - `lines_wide`: Wide tolerance for merged cells
   - **NEW: `text_liberal`**: Liberal spacing for wrapped content
   - **NEW: `lines_extra_wide`**: Maximum flexibility for tight/low-res formats

### 2. **Enhanced Word Grouping for Wrapped Text**
   - Improved `group_words_into_rows()` with adaptive y-tolerance
   - Better handling of variable row heights
   - Accounts for wrapped/multi-line cell content
   - Detects and groups words that belong to the same row even with unusual spacing

### 3. **Enhanced Column Boundary Detection**
   - New `detect_column_boundaries_enhanced()` function
   - Analyzes spacing patterns between header columns
   - Better handles tightly-spaced and loosely-spaced headers
   - Improved word-to-column assignment with `assign_word_to_col_enhanced()`

### 4. **Improved Continuation Row Detection**
   - Enhanced `is_continuation_row()` with better logic
   - Checks for date presence with more nuance
   - Detects amount values more reliably
   - Filters out noise and empty content better

### 5. **Better Multi-line Header Support**
   - `merge_split_header_rows()` now handles more scenarios
   - Checks rows 2-3 for headers (not just rows 0-1)
   - Better combined text validation
   - Handles headers like "TRANSACTION DETAILS" split across rows

### 6. **Enhanced Text-based Parsing**
   - Improved `parse_text_statement()` for wrapped descriptions
   - Collects continuation lines for multi-line descriptions
   - Better stops at transaction boundaries
   - More flexible whitespace handling

### 7. **Improved Header Recognition**
   - `is_header_like()` now recognizes more variations:
     - "Debits" / "Credits" (plural forms)
     - "Details" / "Description"
     - "Ref" / "Reference"
   - More flexible pattern matching

### 8. **Enhanced Table Extraction**
   - `extract_table_from_text_positions()` improved for flexible formats
   - More tolerant y-tolerance for row grouping (8 instead of 5)
   - Better fallback when pdfplumber's table strategies fail
   - Improved cell content aggregation

### 9. **Robustness Improvements**
   - Better None/empty cell handling throughout
   - More defensive coding for edge cases
   - Better error handling in table cleaning
   - Improved amount parsing with flexible patterns

## Format Examples Now Supported

### Standard Well-Structured Format
```
Date | Transaction Details | Debits | Credits | Balance
01 Feb, 2026 | OPENING BALANCE | - | - | 0.00
05 Feb, 2026 | UPI/T Pragadeesh | 9,000.00 | - | 9,000.00
```

### NEW: Flexible/Wrapped Format
```
Date             Transaction Details                          Debits        Credits       Balance
06 Feb 2026      YESBOPTUPI/BP
                 payment18bda0ynz@paytm                       INR 200.00    -             INR 9.37
                 
08 Feb 2026      HDFCL000067/PRAVEEN
                 R K /XXXXX56991/praveenr609
                 91@okaxis                                    -             INR 6,500.00  INR 6,509.37
```

### Key Features of New Support
- ✅ Multi-line transaction descriptions
- ✅ Wrapped text across multiple lines
- ✅ Variable column spacing
- ✅ Inconsistent row heights
- ✅ Mixed formatting within same document
- ✅ INR-prefix amounts (e.g., "INR 200.00")
- ✅ Signed amounts (e.g., "+9,000.00")
- ✅ Flexible whitespace and alignment

## Backward Compatibility
✅ All existing functionality preserved
✅ All original format support maintained
✅ No breaking changes to API
✅ Enhanced fallback mechanisms when primary strategies fail

## Testing Recommendations
1. Test with the flexible/wrapped format statements
2. Verify multi-line descriptions are merged correctly
3. Check that amounts are parsed correctly regardless of prefix
4. Validate that wrapped text doesn't break categorization
5. Test with mixed formats in same PDF

## Performance Considerations
- Slightly increased processing time due to additional strategies
- Additional text position fallback may be slower for very large documents
- All optimization remains in place (deduplication, early termination)

## Implementation Details
- Updated version tag in docstring: v4 → v5
- Added comments explaining new logic throughout
- Follows existing code style and conventions
- No external dependencies added

---
**Updated**: Document reflects bank_parser.py enhancements for flexible format support.
