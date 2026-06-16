import csv
import io
import logging
import os
import xml.etree.ElementTree as ET

import pandas as pd
import pdfplumber

logger = logging.getLogger(__name__)


def read_any_file(file_path: str, nrows: int = None) -> pd.DataFrame:
    """
    Reads a supported file into a DataFrame.
    nrows: if set, read only first N rows (for mapping discovery).

    Supported: .csv, .xlsx, .xls, .pdf, .txt, .xml, .lin
    """
    lower = file_path.lower()

    try:
        if lower.endswith(".csv"):
            return _read_csv_robust(file_path, nrows)

        if lower.endswith(".xlsx"):
            return _read_excel_robust(file_path, "openpyxl", nrows)

        if lower.endswith(".xls"):
            return _read_excel_robust(file_path, "xlrd", nrows)

        if lower.endswith(".pdf"):
            return _read_pdf(file_path, nrows)

        if lower.endswith(".xml"):
            return _read_xml(file_path, nrows)

        if lower.endswith(".txt") or lower.endswith(".lin"):
            return _read_csv_robust(file_path, nrows, fallback_sep=None)

        raise Exception(f"Unsupported file type: {file_path}")

    except Exception as e:
        raise Exception(f"Failed to read file {file_path}: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# CSV / TXT / LIN
# ─────────────────────────────────────────────────────────────────────────────

def _read_csv_robust(file_path: str, nrows: int, fallback_sep=",") -> pd.DataFrame:
    """
    Robust CSV/delimited text reader.
    - Auto-detects delimiter via Sniffer.
    - Scans first 100 lines to find the real header row (max number of non-empty cols).
    - Handles mid-file repeated column headers.
    """
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        sample = f.read(8192)
        f.seek(0)

        try:
            dialect = csv.Sniffer().sniff(sample)
            sep = dialect.delimiter
        except Exception:
            sep = fallback_sep or ","

        lines = [line.rstrip("\n\r") for line in f.readlines()]

    if not lines:
        return pd.DataFrame()

    # Find the row with the most non-empty delimited columns → use as header
    max_cols = 0
    header_idx = 0
    for i, line in enumerate(lines[:100]):
        if not line.strip():
            continue
        cols = [c for c in line.split(sep) if c.strip()]
        if len(cols) > max_cols:
            max_cols = len(cols)
            header_idx = i

    df = pd.read_csv(
        file_path,
        sep=sep,
        skiprows=header_idx,
        nrows=nrows,
        skip_blank_lines=True,
        encoding="utf-8",
        on_bad_lines="skip",
        engine="python",
    )

    df = _clean_raw_df(df)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# EXCEL
# ─────────────────────────────────────────────────────────────────────────────

def _read_excel_robust(file_path: str, engine: str, nrows: int = None) -> pd.DataFrame:
    """
    Robust Excel reader.
    - Scans first 50 rows to detect the real header row.
    - Handles blank rows, merged cells, and mid-file repeated headers.
    """
    # Read raw without header first, up to 50+nrows rows
    scan_rows = 50
    try:
        raw = pd.read_excel(
            file_path,
            engine=engine,
            header=None,
            nrows=scan_rows + (nrows or 0),
        )
    except Exception as e:
        raise Exception(f"Excel read error: {e}")

    if raw.empty:
        return pd.DataFrame()

    # Find the header row: row with the most non-null, non-numeric string values
    best_row = 0
    best_score = 0
    for i in range(min(scan_rows, len(raw))):
        row = raw.iloc[i]
        score = sum(
            1 for v in row
            if pd.notna(v) and isinstance(v, str) and v.strip()
        )
        if score > best_score:
            best_score = score
            best_row = i

    # Use best_row as header
    df = pd.read_excel(
        file_path,
        engine=engine,
        header=best_row,
        nrows=nrows,
    )

    df = _clean_raw_df(df)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# PDF
# ─────────────────────────────────────────────────────────────────────────────

def _read_pdf(file_path: str, nrows: int = None) -> pd.DataFrame:
    rows = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if table:
                rows.extend(table)
            if nrows and len(rows) > nrows + 1:
                break

    if not rows:
        raise Exception("No tabular data found in PDF")

    cleaned = [r for r in rows if any(cell and str(cell).strip() for cell in r)]
    if not cleaned:
        return pd.DataFrame()

    header = cleaned[0]
    data = cleaned[1:]
    if nrows:
        data = data[:nrows]

    df = pd.DataFrame(data, columns=header)
    df = _clean_raw_df(df)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# XML
# ─────────────────────────────────────────────────────────────────────────────

def _read_xml(file_path: str, nrows: int = None) -> pd.DataFrame:
    """
    Parse XML as a DataFrame.
    Strategy: find all leaf-record elements and extract their children as columns.
    Falls back to CSV-style parsing if XML is malformed.
    """
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()

        # Find repeating child elements (records)
        # Heuristic: children of root with sub-children, or root itself if flat
        records = []

        def extract_records(node, depth=0):
            children = list(node)
            if not children:
                return
            # Check if children look like records (each has sub-children or text)
            for child in children:
                sub = list(child)
                if sub:
                    row = {}
                    for item in sub:
                        row[item.tag] = item.text
                    records.append(row)
                else:
                    # leaf element — treat parent's children as one record
                    break

        extract_records(root)

        if not records:
            # Flat XML: each direct child of root is a record with attributes/text
            for child in root:
                row = dict(child.attrib)
                row.update({sub.tag: sub.text for sub in child})
                if not row:
                    row["value"] = child.text
                records.append(row)

        df = pd.DataFrame(records)
        if nrows:
            df = df.head(nrows)
        df = _clean_raw_df(df)
        return df

    except ET.ParseError:
        logger.warning(f"XML parse failed for {file_path}, falling back to CSV parser")
        return _read_csv_robust(file_path, nrows)


# ─────────────────────────────────────────────────────────────────────────────
# SHARED CLEANUP
# ─────────────────────────────────────────────────────────────────────────────

def _clean_raw_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Post-read cleanup:
    - Drop fully empty rows
    - Drop fully empty columns
    - Strip column name whitespace
    - Remove duplicate headers that appeared mid-file
    """
    # Strip column names
    df.columns = [str(c).strip() for c in df.columns]

    # Drop fully empty rows and columns
    df = df.dropna(how="all")
    df = df.dropna(axis=1, how="all")

    # Remove rows where all values equal the header (repeated mid-file headers)
    header_vals = set(df.columns)
    mask = df.apply(
        lambda row: set(row.astype(str).str.strip().tolist()) == header_vals,
        axis=1,
    )
    df = df[~mask]

    df = df.reset_index(drop=True)
    return df