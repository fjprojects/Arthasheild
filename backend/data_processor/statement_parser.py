import csv
import io
import os
import re
import tempfile
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple, Union
from pathlib import Path

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError
from pdfminer.pdfdocument import PDFPasswordIncorrect

from .models import NormalizedTransaction, StatementParseResult
from .normalizer import TransactionNormalizer
from .errors import StatementParseError

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_PDF_PAGES = 15
SUPPORTED_EXTENSIONS = {'.csv', '.pdf', '.txt'}

# Header keywords mapping for dynamic column recognition
COLUMN_KEYWORDS = {
    'date': ['date', 'txn date', 'transaction date', 'trans date', 'value date', 'posting date'],
    'description': ['narration', 'description', 'particulars', 'remarks', 'details', 'transaction details', 'transaction remarks'],
    'reference': ['chq/ref no', 'chq / ref no', 'ref no', 'reference', 'chq no', 'cheque no', 'utr', 'txn id', 'transaction id', 'ref'],
    'debit': ['debit', 'withdrawal', 'dr', 'withdrawal amount', 'dr amount', 'paid out', 'debit (inr)'],
    'credit': ['credit', 'deposit', 'cr', 'deposit amount', 'cr amount', 'paid in', 'credit (inr)'],
    'amount': ['amount', 'txn amount', 'transaction amount', 'net amount'],
    'type': ['type', 'dr/cr', 'cr/dr', 'txn type', 'transaction type'],
    'balance': ['balance', 'closing balance', 'avl bal', 'available balance', 'bal']
}

class BankStatementParser:
    """
    Robust multi-format bank statement ingestion engine.
    Supports CSV, PDF, and structured TXT statements with Indian banking formats.
    """

    @classmethod
    def parse_file(cls, file_obj: Any, filename: str) -> StatementParseResult:
        """
        Main entry point for file-based statement ingestion.
        Safely validates file format and size, delegates to format-specific parsers,
        and ensures temporary files are destroyed after processing.
        """
        if not file_obj:
            raise StatementParseError("No file provided for statement parsing.")

        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            # The extension comes from the uploaded file name and is therefore
            # untrusted: it is never echoed back to the client.
            raise StatementParseError(
                "Unsupported file format. Only CSV, PDF, and TXT files are supported."
            )

        # Read content bytes safely to check size
        if hasattr(file_obj, 'size') and file_obj.size > MAX_FILE_SIZE_BYTES:
            raise StatementParseError(f"File size exceeds maximum allowed limit of {MAX_FILE_SIZE_BYTES // (1024*1024)}MB.")

        if hasattr(file_obj, 'read'):
            content = file_obj.read()
        elif isinstance(file_obj, (bytes, bytearray)):
            content = bytes(file_obj)
        else:
            raise StatementParseError("Invalid file object provided.")

        if len(content) == 0:
            raise StatementParseError("The uploaded statement file is empty (0 bytes).")

        if len(content) > MAX_FILE_SIZE_BYTES:
            raise StatementParseError(f"File size exceeds maximum allowed limit of {MAX_FILE_SIZE_BYTES // (1024*1024)}MB.")

        # Validate file signature / magic bytes to prevent extension spoofing
        if ext == '.pdf':
            if not (content.startswith(b'%PDF-') or b'%PDF-' in content[:1024]):
                raise StatementParseError("Invalid PDF file signature. Content does not match PDF format.")
        elif ext in ('.csv', '.txt'):
            if b'\x00' in content:
                raise StatementParseError(f"Invalid {ext.upper()[1:]} file content. Binary data detected.")

        # Dispatch based on extension
        if ext == '.csv':
            return cls.parse_csv_bytes(content)
        elif ext == '.pdf':
            return cls.parse_pdf_bytes(content)
        elif ext == '.txt':
            return cls.parse_txt_bytes(content)
        else:
            raise StatementParseError("Unsupported file format. Only CSV, PDF, and TXT files are supported.")

    @classmethod
    def parse_csv_bytes(cls, content_bytes: bytes) -> StatementParseResult:
        """
        Parses CSV statement bytes with auto-detection of metadata preambles and table columns.
        """
        try:
            text = content_bytes.decode('utf-8')
        except UnicodeDecodeError:
            try:
                text = content_bytes.decode('latin-1')
            except Exception:
                # The decoder message can quote the offending bytes: it is
                # never echoed back to the client.
                raise StatementParseError("Unable to decode CSV file: unsupported character encoding.")

        return cls.parse_csv_text(text)

    @classmethod
    def parse_csv_text(cls, text: str) -> StatementParseResult:
        """
        Parses CSV text into a structured StatementParseResult.
        """
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            raise StatementParseError("Statement content is empty.")

        account_info = cls._extract_metadata_from_lines(lines)
        reader = csv.reader(lines)
        rows = list(reader)

        header_idx, col_map = cls._find_table_header(rows)
        if header_idx is None:
            raise StatementParseError("Could not detect transaction table header in CSV statement.")

        transactions: List[NormalizedTransaction] = []
        errors: List[str] = []

        data_rows = rows[header_idx + 1:]
        for idx, row in enumerate(data_rows, start=header_idx + 2):
            if not row or all(not cell.strip() for cell in row):
                continue

            parsed_tx = cls._parse_single_row(row, col_map, f"CSV Row {idx}", source="STATEMENT_CSV")
            if parsed_tx:
                transactions.append(parsed_tx)
            else:
                # If row looks like a footer or summary, ignore; else log error.
                # The warning keeps the row number (which identifies the problem)
                # but never reproduces the row content.
                row_str = " ".join(row).lower()
                if not any(k in row_str for k in ['total', 'opening balance', 'closing balance', 'page']):
                    errors.append(f"Row {idx}: Failed to extract a valid transaction.")

        if not transactions:
            raise StatementParseError("No valid transactions found in the CSV statement.")

        # Deduplicate
        unique_txs, dups = TransactionNormalizer.deduplicate_transactions(transactions)
        total_debits = sum(t.amount for t in unique_txs if t.transaction_type == 'DEBIT')
        total_credits = sum(t.amount for t in unique_txs if t.transaction_type == 'CREDIT')

        return StatementParseResult(
            transactions=unique_txs,
            account_info=account_info,
            total_debits=total_debits,
            total_credits=total_credits,
            net_flow=total_credits - total_debits,
            raw_row_count=len(data_rows),
            parsed_count=len(unique_txs),
            errors=errors,
            format_detected="CSV"
        )

    @classmethod
    def parse_pdf_bytes(cls, content_bytes: bytes) -> StatementParseResult:
        """
        Parses PDF bank statements using pdfplumber.
        Guarantees that temporary files on disk are destroyed in a finally: block.
        """
        temp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        try:
            temp_pdf.write(content_bytes)
            temp_pdf.flush()
            temp_pdf.close()

            return cls._parse_pdf_path(temp_pdf.name)
        finally:
            # Guarantee permanent deletion of temporary PDF file
            if os.path.exists(temp_pdf.name):
                try:
                    os.unlink(temp_pdf.name)
                except OSError:
                    pass

    @classmethod
    def _parse_pdf_path(cls, pdf_path: str) -> StatementParseResult:
        """
        Extracts tables and metadata from a PDF file.
        """
        try:
            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) == 0:
                    raise StatementParseError("The uploaded PDF statement has 0 pages.")
                if len(pdf.pages) > MAX_PDF_PAGES:
                    raise StatementParseError(f"PDF exceeds maximum allowed page limit of {MAX_PDF_PAGES} pages.")

                all_text = ""
                all_table_rows: List[List[str]] = []

                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    all_text += page_text + "\n"

                    tables = page.extract_tables()
                    for table in tables:
                        for row in table:
                            cleaned_row = [str(cell).strip() if cell is not None else "" for cell in row]
                            if any(cleaned_row):
                                all_table_rows.append(cleaned_row)

        except StatementParseError:
            # A controlled message from our own parser (page limit, empty
            # document, ...) is returned as-is: it never carries content.
            raise
        except PDFPasswordIncorrect:
            raise StatementParseError("Password-protected PDF statements are not supported. Please upload an unprotected PDF.")
        except PDFSyntaxError:
            # The parser message can quote document content: it is not echoed.
            raise StatementParseError("Corrupted or invalid PDF file.")
        except Exception as e:
            if "password" in str(e).lower():
                raise StatementParseError("Password-protected PDF statements are not supported.")
            raise StatementParseError("Failed to process PDF statement.")

        account_info = cls._extract_metadata_from_lines(all_text.splitlines())

        # If pdfplumber successfully extracted structured tables
        if all_table_rows:
            header_idx, col_map = cls._find_table_header(all_table_rows)
            if header_idx is not None:
                transactions: List[NormalizedTransaction] = []
                errors: List[str] = []

                data_rows = all_table_rows[header_idx + 1:]
                for idx, row in enumerate(data_rows, start=header_idx + 2):
                    if not row or all(not cell.strip() for cell in row):
                        continue
                    parsed_tx = cls._parse_single_row(row, col_map, f"PDF Row {idx}", source="STATEMENT_PDF")
                    if parsed_tx:
                        transactions.append(parsed_tx)

                if transactions:
                    unique_txs, _ = TransactionNormalizer.deduplicate_transactions(transactions)
                    total_debits = sum(t.amount for t in unique_txs if t.transaction_type == 'DEBIT')
                    total_credits = sum(t.amount for t in unique_txs if t.transaction_type == 'CREDIT')

                    return StatementParseResult(
                        transactions=unique_txs,
                        account_info=account_info,
                        total_debits=total_debits,
                        total_credits=total_credits,
                        net_flow=total_credits - total_debits,
                        raw_row_count=len(data_rows),
                        parsed_count=len(unique_txs),
                        errors=errors,
                        format_detected="PDF_TABLE"
                    )

        # Fallback 1: If text lines contain comma, tab, or pipe delimited table structures
        delim_lines = [l for l in all_text.splitlines() if ',' in l or '\t' in l or '|' in l]
        if len(delim_lines) >= 2:
            try:
                res = cls.parse_csv_text(all_text)
                res.format_detected = "PDF_TEXT_DELIMITED"
                res.account_info.update(account_info)
                for tx in res.transactions:
                    tx.source = "STATEMENT_PDF"
                return res
            except Exception:
                pass

        # Fallback 2: Parse line-by-line text if PDF has un-bordered / freeform layout
        return cls._parse_text_lines_fallback(all_text.splitlines(), account_info, source="STATEMENT_PDF")

    @classmethod
    def parse_txt_bytes(cls, content_bytes: bytes) -> StatementParseResult:
        """
        Parses plain text / CSV-like bank statement dumps.
        """
        try:
            text = content_bytes.decode('utf-8')
        except UnicodeDecodeError:
            text = content_bytes.decode('latin-1', errors='replace')

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            raise StatementParseError("Text statement content is empty.")

        account_info = cls._extract_metadata_from_lines(lines)

        # Check if lines look like comma or tab or pipe delimited
        delimiter = ','
        first_delim_line = next((l for l in lines if ',' in l or '\t' in l or '|' in l), None)
        if first_delim_line:
            if '\t' in first_delim_line:
                delimiter = '\t'
            elif '|' in first_delim_line:
                delimiter = '|'

        if delimiter != ',':
            # Convert to CSV reader format
            rows = [line.split(delimiter) for line in lines]
            rows = [[c.strip() for c in r] for r in rows]
            header_idx, col_map = cls._find_table_header(rows)
            if header_idx is not None:
                transactions: List[NormalizedTransaction] = []
                data_rows = rows[header_idx + 1:]
                for idx, row in enumerate(data_rows):
                    tx = cls._parse_single_row(row, col_map, f"TXT Row {idx}", source="STATEMENT_TXT")
                    if tx:
                        transactions.append(tx)

                if transactions:
                    unique_txs, _ = TransactionNormalizer.deduplicate_transactions(transactions)
                    total_debits = sum(t.amount for t in unique_txs if t.transaction_type == 'DEBIT')
                    total_credits = sum(t.amount for t in unique_txs if t.transaction_type == 'CREDIT')
                    return StatementParseResult(
                        transactions=unique_txs,
                        account_info=account_info,
                        total_debits=total_debits,
                        total_credits=total_credits,
                        net_flow=total_credits - total_debits,
                        raw_row_count=len(data_rows),
                        parsed_count=len(unique_txs),
                        format_detected="TXT_DELIMITED"
                    )

        # Fallback: Standard CSV or Line parsing
        try:
            return cls.parse_csv_text(text)
        except ValueError:
            return cls._parse_text_lines_fallback(lines, account_info, source="STATEMENT_TXT")

    # ==================== INTERNAL HELPER METHODS ====================

    @classmethod
    def _find_table_header(cls, rows: List[List[str]]) -> Tuple[Optional[int], Dict[str, int]]:
        """
        Scans rows to find the transaction table header row and map column indices.
        """
        for idx, row in enumerate(rows[:30]):  # check up to first 30 rows
            cleaned_cells = [c.lower().strip() for c in row if c]
            if len(cleaned_cells) < 2:
                continue

            col_map: Dict[str, int] = {}
            for col_idx, cell in enumerate(row):
                cell_clean = cell.lower().strip()
                if not cell_clean:
                    continue

                for field, keywords in COLUMN_KEYWORDS.items():
                    if field not in col_map:
                        if any(kw == cell_clean or cell_clean.startswith(kw) for kw in keywords):
                            col_map[field] = col_idx

            # A valid header must have at least a date column AND an amount or debit/credit column
            has_date = 'date' in col_map
            has_amt = 'amount' in col_map or 'debit' in col_map or 'credit' in col_map
            if has_date and has_amt:
                return idx, col_map

        return None, {}

    @classmethod
    def _parse_single_row(
        cls,
        row: List[str],
        col_map: Dict[str, int],
        row_id: str,
        source: str
    ) -> Optional[NormalizedTransaction]:
        """
        Parses a single row into a NormalizedTransaction according to col_map.
        """
        date_idx = col_map.get('date')
        if date_idx is None or date_idx >= len(row):
            return None

        raw_date = row[date_idx].strip()
        if not raw_date:
            return None

        try:
            parsed_date = TransactionNormalizer.parse_date(raw_date)
        except ValueError:
            return None

        # Description
        desc_idx = col_map.get('description')
        raw_desc = row[desc_idx].strip() if desc_idx is not None and desc_idx < len(row) else "Bank Transaction"
        if not raw_desc:
            raw_desc = "Bank Transaction"

        # Reference
        ref_idx = col_map.get('reference')
        ref_id = row[ref_idx].strip() if ref_idx is not None and ref_idx < len(row) else None
        if not ref_id:
            ref_id = TransactionNormalizer.extract_reference_id(raw_desc)

        # Amount and direction extraction
        debit_idx = col_map.get('debit')
        credit_idx = col_map.get('credit')
        amount_idx = col_map.get('amount')
        type_idx = col_map.get('type')
        balance_idx = col_map.get('balance')

        parsed_amount: Optional[Decimal] = None
        direction: Optional[str] = None

        # 1. Separate Debit and Credit columns
        if debit_idx is not None and credit_idx is not None:
            raw_debit = row[debit_idx].strip() if debit_idx < len(row) else ""
            raw_credit = row[credit_idx].strip() if credit_idx < len(row) else ""

            if raw_debit and raw_debit not in ('-', '0', '0.00', '0.0'):
                try:
                    parsed_amount, _ = TransactionNormalizer.parse_amount(raw_debit)
                    direction = 'DEBIT'
                except ValueError:
                    pass

            if not parsed_amount and raw_credit and raw_credit not in ('-', '0', '0.00', '0.0'):
                try:
                    parsed_amount, _ = TransactionNormalizer.parse_amount(raw_credit)
                    direction = 'CREDIT'
                except ValueError:
                    pass

        # 2. Single Amount column with Type or Dr/Cr indicator
        if parsed_amount is None and amount_idx is not None and amount_idx < len(row):
            raw_amt = row[amount_idx].strip()
            if raw_amt and raw_amt != '-':
                try:
                    parsed_amount, dir_hint = TransactionNormalizer.parse_amount(raw_amt)
                    direction = dir_hint
                except ValueError:
                    pass

                # If no direction hint in amount, check type column
                if not direction and type_idx is not None and type_idx < len(row):
                    type_str = row[type_idx].lower().strip()
                    if 'dr' in type_str or 'debit' in type_str or 'w' in type_str:
                        direction = 'DEBIT'
                    elif 'cr' in type_str or 'credit' in type_str or 'd' in type_str:
                        direction = 'CREDIT'

        if parsed_amount is None or parsed_amount == Decimal('0'):
            return None

        if not direction:
            # Default to DEBIT if cannot be determined, but check description
            if re.search(r'\b(?:sal|salary|refund|cashback|interest|deposit|reversal)\b', raw_desc, re.IGNORECASE):
                direction = 'CREDIT'
            else:
                direction = 'DEBIT'

        # Balance
        parsed_balance = None
        if balance_idx is not None and balance_idx < len(row):
            raw_bal = row[balance_idx].strip()
            if raw_bal:
                try:
                    parsed_balance, _ = TransactionNormalizer.parse_amount(raw_bal)
                except ValueError:
                    pass

        return NormalizedTransaction(
            transaction_id="",
            transaction_date=parsed_date,
            description=raw_desc,
            amount=parsed_amount,
            transaction_type=direction,
            source=source,
            merchant=TransactionNormalizer.extract_merchant(raw_desc),
            reference_id=ref_id,
            currency="INR",
            available_balance=parsed_balance,
            raw_source=f"{row_id}: {' | '.join(row)}"
        )

    @classmethod
    def _parse_text_lines_fallback(
        cls,
        lines: List[str],
        account_info: Dict[str, Any],
        source: str
    ) -> StatementParseResult:
        """
        Fallback parser for unformatted or space-aligned text statements.
        """
        transactions: List[NormalizedTransaction] = []
        date_pattern = re.compile(r'\b(?:\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[/-][A-Za-z]{3,9}[/-]\d{2,4})\b')
        amount_pattern = re.compile(r'(?:INR|Rs\.?|₹)?\s*(\d{1,3}(?:,\d{2,3})*(?:\.\d{2})?)\s*(Dr|Cr)?\b', re.IGNORECASE)

        for line in lines:
            line_str = line.strip()
            date_match = date_pattern.search(line_str)
            if not date_match:
                continue

            raw_date = date_match.group(0)
            try:
                parsed_date = TransactionNormalizer.parse_date(raw_date)
            except ValueError:
                continue

            # Look for amounts in remainder of line
            rest_of_line = line_str[date_match.end():]
            amt_matches = list(amount_pattern.finditer(rest_of_line))
            if not amt_matches:
                continue

            first_amt = amt_matches[0]
            try:
                amt_str = first_amt.group(1)
                dr_cr = first_amt.group(2)
                parsed_amt, _ = TransactionNormalizer.parse_amount(amt_str)
            except ValueError:
                continue

            direction = 'CREDIT' if dr_cr and 'cr' in dr_cr.lower() else 'DEBIT'
            desc = rest_of_line[:first_amt.start()].strip()
            if not desc:
                desc = "Bank Transaction"

            transactions.append(NormalizedTransaction(
                transaction_id="",
                transaction_date=parsed_date,
                description=desc,
                amount=parsed_amt,
                transaction_type=direction,
                source=source,
                merchant=TransactionNormalizer.extract_merchant(desc),
                reference_id=TransactionNormalizer.extract_reference_id(desc),
                currency="INR",
                raw_source=line_str
            ))

        if not transactions:
            raise StatementParseError("No valid transactions found in statement.")

        unique_txs, _ = TransactionNormalizer.deduplicate_transactions(transactions)
        total_debits = sum(t.amount for t in unique_txs if t.transaction_type == 'DEBIT')
        total_credits = sum(t.amount for t in unique_txs if t.transaction_type == 'CREDIT')

        return StatementParseResult(
            transactions=unique_txs,
            account_info=account_info,
            total_debits=total_debits,
            total_credits=total_credits,
            net_flow=total_credits - total_debits,
            raw_row_count=len(lines),
            parsed_count=len(unique_txs),
            format_detected="TEXT_FALLBACK"
        )

    @classmethod
    def _extract_metadata_from_lines(cls, lines: List[str]) -> Dict[str, Any]:
        """
        Scans preliminary lines to extract bank name, account number, IFSC, and customer details.
        """
        metadata: Dict[str, Any] = {}
        for line in lines[:25]:
            # Bank name
            if 'bank' in line.lower() and 'bank_name' not in metadata:
                match = re.search(r'([A-Za-z ]{3,30}\bBank\b)', line, re.IGNORECASE)
                if match:
                    metadata['bank_name'] = match.group(1).strip()

            # Account number
            acct_match = re.search(r'(?:(?:A/c|A/C|Account|Acct|Acc\s*No|ACC|Account\s*Number)[\s.:#-]*)([0-9Xx*-]{8,24})', line, re.IGNORECASE)
            if acct_match and 'account_number' not in metadata:
                raw_acct = acct_match.group(1).strip()
                # Store masked
                metadata['masked_account_number'] = f"XX..{raw_acct[-4:]}" if len(raw_acct) >= 4 else "XX..MASKED"

            # IFSC
            ifsc_match = re.search(r'\b([A-Z]{4}0[A-Z0-9]{6})\b', line, re.IGNORECASE)
            if ifsc_match and 'ifsc_code' not in metadata:
                metadata['ifsc_code'] = ifsc_match.group(1).strip().upper()

        return metadata
