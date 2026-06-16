import hashlib
import json
import logging
import pandas as pd

logger = logging.getLogger(__name__)


def clean_mapped_dataframe(df: pd.DataFrame, mapping: dict, side: str, progress_cb=None) -> list:
    """
    Clean and format a raw DataFrame using the provided column mapping.

    Returns a list of dicts ready for DB insertion.

    Mapping structure (updated to support per-side date formats):
    {
      "source": {
        "datetime": "col",
        "amount": "col",
        "references": ["col1", ...],
        "date_format": "%d/%m/%Y",   # optional, per-side override
        "date_mode": "date"          # optional, per-side override
      },
      "dest": {
        "datetime": "col",
        "amount": "col",
        "references": ["col1", ...],
        "date_format": "%m/%d/%Y",   # can differ from source!
        "date_mode": "datetime"
      },
      "date_mode": "date" | "datetime",   # global fallback, default "datetime"
      "date_format": "%d/%m/%Y"           # global fallback, optional
    }

    Per-side settings take priority over global settings.
    """
    m = mapping[side]
    
    if progress_cb:
        progress_cb(f"Cleaning {side} dataframe...", 15 if side == "source" else 30)

    date_col = m["datetime"]
    amount_col = m["amount"]
    ref_cols = m.get("references", [])

    # Per-side date settings take priority over global fallbacks
    # This allows source and destination to have different date formats
    date_mode = m.get("date_mode") or mapping.get("date_mode", "datetime")
    date_format = m.get("date_format") or mapping.get("date_format", None)

    # All mapped columns
    all_mapped_cols = [date_col, amount_col] + ref_cols
    remaining_cols = [c for c in df.columns if c not in all_mapped_cols]

    df = df.copy()

    # ── Drop fully blank rows (all mapped columns empty) ──────────────────
    df = df.dropna(subset=all_mapped_cols, how="all")

    # ── 1. Datetime formatting ─────────────────────────────────────────────
    if date_format:
        try:
            df["txn_datetime"] = pd.to_datetime(
                df[date_col], format=date_format, errors="coerce"
            )
        except Exception:
            df["txn_datetime"] = pd.to_datetime(df[date_col], errors="coerce")
    else:
        df["txn_datetime"] = pd.to_datetime(df[date_col], errors="coerce")

    if date_mode == "date":
        # Keep only date portion — normalize to midnight
        df["txn_datetime"] = df["txn_datetime"].dt.normalize()
    else:
        # Datetime mode — floor to minute (ignore seconds per spec)
        df["txn_datetime"] = df["txn_datetime"].dt.floor("min")

    # ── 2. Amount cleaning ────────────────────────────────────────────────
    df["amount_clean"] = (
        df[amount_col]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.strip()
    )
    df["amount_clean"] = pd.to_numeric(df["amount_clean"], errors="coerce")

    # ── 3. References cleaning ────────────────────────────────────────────
    # Convert all references to UPPERCASE as requested
    for col in ref_cols:
        s = df[col].copy()
        # Convert floats that are integers (e.g. 12345.0 -> "12345")
        s = s.apply(
            lambda x: str(int(x)) if isinstance(x, float) and not pd.isna(x) and x == int(x)
            else (str(x).strip() if pd.notna(x) else "")
        )
        df[col] = s.str.strip().str.upper()

    # ── Drop rows where datetime or amount is null ─────────────────────────
    df = df.dropna(subset=["txn_datetime", "amount_clean"])

    logger.info(f"[{side}] Cleaned rows: {len(df)}")

    # ── Build structured records ──────────────────────────────────────────
    records = []
    total_len = len(df)
    for i, (idx, row) in enumerate(df.iterrows()):
        if progress_cb and i > 0 and i % 2000 == 0:
            if side == "source":
                progress_cb(f"Cleaning source data: {i}/{total_len}...", 10 + int((i/total_len)*20))
            else:
                progress_cb(f"Cleaning dest data: {i}/{total_len}...", 60 + int((i/total_len)*25))

        refs = {}
        for col in ref_cols:
            val = str(row[col]).strip()
            if val and val.lower() != "nan":
                refs[col] = val

        rem = {}
        for c in remaining_cols:
            val = row[c]
            if pd.notna(val):
                rem[str(c)] = str(val)

        # Deterministic checksum based on side + datetime + amount + refs
        base_str = f"{side}|{row['txn_datetime']}|{row['amount_clean']}|"
        for k in sorted(refs.keys()):
            base_str += f"{k}:{refs[k]}|"

        checksum = hashlib.md5(base_str.encode("utf-8")).hexdigest()

        records.append({
            "source_row_num": int(idx),
            "txn_datetime": row["txn_datetime"].to_pydatetime() if pd.notna(row["txn_datetime"]) else None,
            "amount": float(row["amount_clean"]) if pd.notna(row["amount_clean"]) else 0.0,
            "references": refs,
            "remaining_columns": rem,
            "checksum": checksum,
        })

    return records