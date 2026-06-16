"""
matching_engine.py — Recon 2.0 Core Matching Logic
====================================================

This module is the HEART of the reconciliation system. It implements a
6-layer waterfall matching pipeline that progressively matches source and
destination financial records from strictest to most flexible.

HOW IT WORKS (Waterfall Architecture):
---------------------------------------
Each layer receives ONLY the rows that were NOT matched by previous layers.
This ensures:
  1. No row is matched more than once.
  2. Each layer only sees genuinely unmatched data.
  3. Results are additive and consistent.

LAYER ORDER (strictest → most flexible):
  Layer 0 — Self Knock:     Matches +/- pairs within the SAME file
  Layer 1 — Exact Match:    Exact ref + amount + datetime on src vs dest
  Layer 2 — Tolerance:      Exact ref, but amount/time within tolerance band
  Layer 3 — Subset (N:M):   Grouped many-to-many: multiple rows on one/both sides
                             share same references and their SUMS match within tol
  Layer 4 — Fuzzy:          Same amount/time, but references are fuzzy-matched
  Layer 5 — LLM:            AI-assisted matching for complex/remaining records

IMPORTANT DESIGN NOTES:
  - Layer 3 intentionally skips 1-to-1 pairs (those are handled by Layer 1/2).
  - All datetime comparisons ignore seconds (floored to minute).
  - Amount comparisons use configurable tolerance (tol_amount).
  - Time comparisons use configurable tolerance (tol_time in minutes).
  - Reference columns are matched exactly unless specified (fuzzy is Layer 4).
"""

import asyncio
import json
import logging
import re
import time

import httpx
import os
import numpy as np
import pandas as pd
# pyrefly: ignore [missing-import]
from rapidfuzz.process import extractOne


class MatchingEngine:
    """
    Orchestrates all matching layers for a single reconciliation run.

    Parameters
    ----------
    tol_amount : float
        Maximum allowed absolute difference in amount between matched records.
        E.g. tol_amount=10 means amounts within ±10 are considered matching.

    tol_time : int
        Maximum allowed time difference in MINUTES between matched records.
        E.g. tol_time=60 means datetimes within 1 hour are considered matching.

    mapping : dict
        Column mapping configuration in the form:
        {
          "source": {"datetime": "col", "amount": "col", "references": ["col1", ...]},
          "dest":   {"datetime": "col", "amount": "col", "references": ["col1", ...]},
          "date_mode": "date" | "datetime",
          "date_format": "%d/%m/%Y"   # optional
        }
    """

    def __init__(self, tol_amount, tol_time, mapping):
        self.tol_amount = float(tol_amount)
        self.tol_time_minutes = int(tol_time)
        self.tol_time = pd.Timedelta(minutes=tol_time)

        # Reference column names as defined in the column mapping.
        # Source refs and dest refs may have different column names but represent
        # the same business concept (e.g. "TxnRef" on source, "Reference" on dest).
        self.src_refs = mapping["source"]["references"]
        self.dest_refs = mapping["dest"]["references"]

    # ============================================================
    # HELPERS
    # ============================================================

    def _normalize_ref_key(self, key):
        """
        Ensure groupby keys are always tuples, even for single-column groups.
        pandas groupby returns a scalar when grouping by a single column,
        but a tuple when grouping by multiple columns. This normalizes both
        cases to a tuple so downstream code can handle them uniformly.
        """
        if isinstance(key, tuple):
            return key
        return (key,)

    def _prepare_df(self, df: pd.DataFrame, ref_cols):
        """
        Standardize a DataFrame before any matching layer processes it.

        Steps:
          1. Parse 'datetime' column to pandas Timestamp, floor to minute
             (we intentionally ignore seconds as per business spec).
          2. Parse 'amount' column to numeric float.
          3. Drop any rows where critical matching columns are null
             (datetime, amount, or any reference column).

        Returns a clean copy — does NOT modify the original.
        """
        df = df.copy()

        # Floor datetime to minute — seconds are irrelevant for reconciliation
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce").dt.floor("min")

        # Ensure amount is numeric (handles strings like "1,234.56")
        if "amount" in df.columns:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

        # Create order-independent composite reference key
        # We sort the values so that column selection order doesn't matter.
        df["_ref_key"] = df[ref_cols].apply(
            lambda row: tuple(sorted([str(v).strip().upper() for c, v in row.items() if c in ref_cols and pd.notna(v) and str(v).strip() != ""])),
            axis=1
        )

        # Define which columns must be non-null for a record to participate in matching
        needed = list(ref_cols) + ["datetime", "amount"]
        needed = [c for c in needed if c in df.columns]

        # Drop rows with ANY null in critical columns — cannot match incomplete records
        if needed:
            df = df.dropna(subset=needed)

        return df

    def _rename_dest_refs(self, dest: pd.DataFrame) -> pd.DataFrame:
        # No longer needed since we use order-independent _ref_key
        return dest
    def _make_json_safe(self, df: pd.DataFrame):
        """
        Convert a DataFrame to a list of dicts safe for JSON serialization.
        All values are cast to strings to avoid issues with:
          - pandas Timestamp objects
          - numpy int64/float64 types
          - NaT / NaN values
        Used when sending data to the LLM API.
        """
        safe_rows = []
        for _, row in df.iterrows():
            safe_row = {}
            for k, v in row.to_dict().items():
                safe_row[k] = str(v)
            safe_rows.append(safe_row)
        return safe_rows

    def _build_llm_prompt(self, src_json, dest_json):
        """
        Build the prompt sent to the LLM for Layer 5 matching.
        The LLM is given both source and destination record batches and
        asked to identify matching pairs with a structured JSON response.
        """
        return f"""
You are a financial reconciliation engine.

Match transactions between SOURCE and DEST.

STRICT RULES:
- Amount must match EXACTLY or within tolerance
- Datetime difference must be within tolerance
- References can be fuzzy
- Group rows if needed (subset matching allowed)
- Ignore seconds in datetime; compare only up to minute precision

SOURCE:
{json.dumps(src_json, indent=2)}

DEST:
{json.dumps(dest_json, indent=2)}

OUTPUT STRICT JSON:
[
  {{
    "match_type": "one-to-one|one-to-many|many-to-one|many-to-many",
    "source_indices": [0],
    "dest_indices": [1,2],
    "confidence_score": 0.95,
    "reason": "..."
  }}
]

Return [] if no match.
"""

    def _parse_llm_json(self, text):
        """
        Safely parse JSON returned by the LLM.
        Handles common LLM output issues:
          - Wrapped in markdown code fences (```json ... ```)
          - Extra explanatory text before/after the JSON array
          - Malformed JSON (falls back to empty list)
        """
        if not text:
            return []

        cleaned = text.strip()

        # Remove markdown code fences if present
        cleaned = re.sub(r"^```json", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^```", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

        # Try parsing the whole text as JSON first
        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            pass

        # Fall back: extract the first [...] array found in the text
        first = cleaned.find("[")
        last = cleaned.rfind("]")
        if first != -1 and last != -1 and last > first:
            snippet = cleaned[first:last + 1]
            try:
                parsed = json.loads(snippet)
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return []

        return []

    # ============================================================
    # LAYER 0 — SELF KNOCK
    # ============================================================
    # PURPOSE:
    #   Find rows within the SAME file (source OR destination) where
    #   a positive amount and a negative amount cancel each other out.
    #   These represent internal reversals / corrections.
    #
    # BUSINESS EXAMPLE:
    #   A bank posts a payment of +1000, then reverses it with -1000.
    #   Both entries share the same reference and date. These should be
    #   "self-knocked" (reconciled internally) before comparing to the
    #   other side.
    #
    # MATCH CRITERIA (ALL must be true for a pair to qualify):
    #   - Same reference column values
    #   - Same datetime (floored to minute)
    #   - Exactly 2 rows in the group
    #   - One positive, one negative amount
    #   - sum(amounts) == 0 (i.e. they exactly cancel)
    #
    # NOTE: This runs separately on source (layer0_self_knock) and
    #       destination (layer0_self_knock_dest) DataFrames.
    #       Results from both are combined and those rows are excluded
    #       from all subsequent layers.
    # ============================================================
    def layer0_self_knock(self, df: pd.DataFrame):
        logging.info(f"Layer 0 (Self Knock) started with {len(df)} rows")
        group_cols = ["_ref_key", "datetime"]

        df_clean = self._prepare_df(df, self.src_refs)

        if df_clean.empty:
            return pd.DataFrame()

        grp = df_clean.groupby(group_cols)["amount"]

        # Compute group-level statistics using transform (keeps original row index)
        size = grp.transform("size")           # number of rows in each group
        total = grp.transform("sum")           # sum of amounts in each group
        pos_count = grp.transform(lambda x: (x > 0).sum())   # rows with positive amount
        neg_count = grp.transform(lambda x: (x < 0).sum())   # rows with negative amount

        # Apply all conditions as a boolean mask
        mask = (
            (size == 2) &                   # exactly 2 rows (one +, one -)
            (total.round(2) == 0) &         # amounts cancel out
            (pos_count == 1) &              # exactly one positive
            (neg_count == 1)                # exactly one negative
        )

        return df_clean[mask].copy()

    # ============================================================
    # LAYER 0 (DEST SIDE) — SELF KNOCK ON DESTINATION
    # ============================================================
    # Same logic as layer0_self_knock but applied to the destination
    # DataFrame, using dest reference column names.
    # ============================================================
    def layer0_self_knock_dest(self, df: pd.DataFrame):
        group_cols = self.dest_refs + ["datetime"]
        df_clean = self._prepare_df(df, self.dest_refs)

        if df_clean.empty:
            return pd.DataFrame()

        grp = df_clean.groupby(group_cols)["amount"]

        size = grp.transform("size")
        total = grp.transform("sum")
        pos_count = grp.transform(lambda x: (x > 0).sum())
        neg_count = grp.transform(lambda x: (x < 0).sum())

        mask = (
            (size == 2) &
            (total.round(2) == 0) &
            (pos_count == 1) &
            (neg_count == 1)
        )

        return df_clean[mask].copy()

    # ============================================================
    # LAYER 1 — EXACT MATCH
    # ============================================================
    # PURPOSE:
    #   Find records where ALL of the following match EXACTLY:
    #     - All mapped reference columns (after renaming dest refs to src names)
    #     - datetime (floored to minute)
    #     - amount (exact numeric equality)
    #
    # MATCH TYPE: Produces all combinations of matching src × dest rows
    #   that share the same key (one-to-one if keys are unique, but if
    #   multiple src/dest rows share the same key, all pairs are returned).
    #
    # ALGORITHM:
    #   1. Build a hash-map from (refs, datetime, amount) → list of src rows
    #   2. Build a hash-map from (refs, datetime, amount) → list of dest rows
    #   3. For each key that appears in BOTH maps, emit all src × dest pairs
    #
    # OUTPUT: DataFrame with columns suffixed _x (source) and _y (dest)
    # ============================================================
    def layer1_exact(self, src: pd.DataFrame, dest: pd.DataFrame):
        logging.info(f"Layer 1 (Exact Match) started | src: {len(src)} dest: {len(dest)}")
        src_work = self._prepare_df(src, self.src_refs)
        dest_work = self._prepare_df(dest, self.dest_refs)

        if src_work.empty or dest_work.empty:
            return pd.DataFrame()

        # Rename dest ref columns to match src ref column names for comparison
        dest_work = self._rename_dest_refs(dest_work)

        # The exact match key: all refs + datetime + amount
        cols = ["_ref_key", "datetime", "amount"]

        # Build hash-maps for O(n) lookup instead of O(n²) nested loops
        src_grouped = {}
        for _, row in src_work.iterrows():
            key = tuple(row[c] for c in cols)
            src_grouped.setdefault(key, []).append(row)

        dest_grouped = {}
        for _, row in dest_work.iterrows():
            key = tuple(row[c] for c in cols)
            dest_grouped.setdefault(key, []).append(row)

        rows = []

        # Only process keys present in BOTH source and destination
        common_keys = set(src_grouped.keys()) & set(dest_grouped.keys())

        for key in common_keys:
            for s_row in src_grouped[key]:
                s_dict = s_row.to_dict()

                for d_row in dest_grouped[key]:
                    d_dict = d_row.to_dict()

                    # Emit a row for each src-dest pair, using _x/_y suffixes
                    rows.append({
                        **{f"{k}_x": v for k, v in s_dict.items()},
                        **{f"{k}_y": v for k, v in d_dict.items()},
                    })

        return pd.DataFrame(rows)

    # ============================================================
    # LAYER 2 — TOLERANCE MATCH
    # ============================================================
    # PURPOSE:
    #   Match records where references match EXACTLY but amount and/or
    #   datetime are within the configured tolerance windows.
    #
    # BUSINESS CASE:
    #   - Payment posted 1 day later than transaction date (time tolerance)
    #   - Bank fee rounds amount slightly differently (amount tolerance)
    #
    # MATCH CRITERIA:
    #   - Reference columns: EXACT match
    #   - Amount: |src_amount - dest_amount| <= tol_amount
    #   - Datetime: |src_datetime - dest_datetime| <= tol_time_minutes
    #
    # OPTIMIZATION:
    #   - Block by ref group (only compare within same reference group)
    #   - Sort dest amounts → binary search for amount window (O(log n))
    #   - Check time tolerance only for amount candidates (reduces work)
    #
    # OUTPUT: DataFrame with _x (source) and _y (dest) suffixed columns
    # ============================================================
    def layer2_tolerance(self, src: pd.DataFrame, dest: pd.DataFrame):
        logging.info(f"Layer 2 (Tolerance) started | src: {len(src)} dest: {len(dest)} | amt_tol: {self.tol_amount} time_tol_min: {self.tol_time_minutes}")
        src_work = self._prepare_df(src, self.src_refs)
        dest_work = self._prepare_df(dest, self.dest_refs)

        if src_work.empty or dest_work.empty:
            return pd.DataFrame()

        dest_work = self._rename_dest_refs(dest_work)

        # Pre-build destination lookup grouped by reference key
        # Within each group, sort by amount for binary search
        dest_groups = {}
        for ref_key, grp in dest_work.groupby(["_ref_key"], observed=True, sort=False):
            ref_key = self._normalize_ref_key(ref_key)
            grp2 = grp.sort_values("amount").reset_index(drop=True).copy()
            grp2["_amount_np"] = grp2["amount"].to_numpy()  # numpy array for searchsorted
            dest_groups[ref_key] = grp2

        matches = []

        for ref_key, s_grp in src_work.groupby(["_ref_key"], observed=True, sort=False):
            ref_key = self._normalize_ref_key(ref_key)

            d_grp = dest_groups.get(ref_key)
            if d_grp is None or d_grp.empty:
                continue  # No dest records with this reference — skip

            d_amounts = d_grp["_amount_np"]

            for _, s_row in s_grp.iterrows():
                s_amt = s_row["amount"]
                s_dt = s_row["datetime"]

                # Binary search: find all dest rows within the amount window
                lo_amt = s_amt - self.tol_amount
                hi_amt = s_amt + self.tol_amount

                left = np.searchsorted(d_amounts, lo_amt, side="left")
                right = np.searchsorted(d_amounts, hi_amt, side="right")

                if left >= right:
                    continue  # No dest row with amount in tolerance window

                # Filter by time tolerance among amount candidates
                candidates = d_grp.iloc[left:right]
                time_mask = (candidates["datetime"] - s_dt).abs() <= self.tol_time
                candidates = candidates[time_mask]

                if candidates.empty:
                    continue

                s_dict = s_row.to_dict()

                for _, d_row in candidates.iterrows():
                    d_dict = d_row.drop(labels=["_amount_np"], errors="ignore").to_dict()

                    matches.append({
                        **{f"{k}_x": v for k, v in s_dict.items()},
                        **{f"{k}_y": v for k, v in d_dict.items()},
                    })

        return pd.DataFrame(matches)

    # ============================================================
    # LAYER 3 — MANY-TO-MANY SUBSET / GROUP MATCH
    # ============================================================
    # PURPOSE:
    #   Match groups of records where individual rows don't match 1:1, but
    #   GROUPS of rows with the same reference share matching SUMMED amounts.
    #
    # BUSINESS CASE (examples from AutoreconSP.txt reference logic):
    #   - ONE source payment of 5000 split into THREE dest entries of 2000+2000+1000
    #     → 1 src row matched to 3 dest rows (1:N)
    #   - THREE source invoices of 1000+1500+2500 settled by ONE dest batch payment of 5000
    #     → 3 src rows matched to 1 dest row (N:1)
    #   - FOUR source rows with total 8000 matched against FIVE dest rows with total 8000
    #     → 4 src rows matched to 5 dest rows (N:M)
    #
    # CRITICAL DESIGN DECISION — Why Layer 3 skips 1:1 pairs:
    #   If both a src group and a dest group each contain exactly 1 row, that
    #   pair was already handled (or should have been) by Layer 1 (exact) or
    #   Layer 2 (tolerance). Including 1:1 here would create duplicate matches.
    #   → We SKIP any matched group pair where BOTH sides have only 1 row.
    #
    # ALGORITHM:
    #   1. Group source rows by [ref_cols] → compute sum(amount), collect row IDs
    #   2. Group dest rows by [ref_cols] → compute sum(amount), collect row IDs
    #   3. For matching ref_keys:
    #      a. Check |src_group_sum - dest_group_sum| <= tol_amount
    #      b. Check min/max datetime of src group vs dest group within tol_time
    #      c. Skip if both groups have exactly 1 row (that's a 1:1, handled above)
    #   4. For each matched group pair, expand all src rows × all dest rows
    #      → These are the actual row-level match pairs written to reconciled_table
    #
    # MATCH CRITERIA:
    #   - Reference columns: EXACT match (group key)
    #   - sum(src group amounts) ≈ sum(dest group amounts) within tol_amount
    #   - Datetime of group representative within tol_time
    #   - Group size: at least one side has > 1 row (true subset/group match)
    #
    # OUTPUT: DataFrame with _x (source) and _y (dest) suffixed columns,
    #         one row per src-row × dest-row pair in the matched groups.
    # ============================================================
    def layer3_subset(self, src: pd.DataFrame, dest: pd.DataFrame):
        logging.info(f"Layer 3 (N:M Subset) started | src: {len(src)} dest: {len(dest)}")
        src_work = self._prepare_df(src, self.src_refs)
        dest_work = self._prepare_df(dest, self.dest_refs)

        if src_work.empty or dest_work.empty:
            return pd.DataFrame()

        cols = ["_ref_key"]
        dest_work = self._rename_dest_refs(dest_work)

        # ── Step 1: Group SOURCE by ref_cols ──────────────────────────────
        # For each group, we need:
        #   - sum(amount): total to match against dest group
        #   - row_count: to skip 1:1 pairs
        #   - all individual rows: for expansion back to row-level pairs
        src_groups_meta = {}   # ref_key → {"sum": float, "rows": [row, ...]}
        for ref_key, grp in src_work.groupby(cols, observed=True, sort=False):
            ref_key = self._normalize_ref_key(ref_key)
            rows_list = [row for _, row in grp.iterrows()]
            src_groups_meta[ref_key] = {
                "sum": float(grp["amount"].sum()),
                "rows": rows_list,
                "count": len(rows_list),
                # Representative datetime: use the mean of all datetimes in group
                # This gives a stable center-point for the time tolerance check
                "repr_dt": grp["datetime"].sort_values().iloc[len(grp) // 2],
            }

        # ── Step 2: Group DESTINATION by ref_cols ─────────────────────────
        dest_groups_meta = {}  # ref_key → {"sum": float, "rows": [row, ...]}
        for ref_key, grp in dest_work.groupby(cols, observed=True, sort=False):
            ref_key = self._normalize_ref_key(ref_key)
            rows_list = [row for _, row in grp.iterrows()]
            dest_groups_meta[ref_key] = {
                "sum": float(grp["amount"].sum()),
                "rows": rows_list,
                "count": len(rows_list),
                "repr_dt": grp["datetime"].sort_values().iloc[len(grp) // 2],
            }

        # ── Step 3: Match groups ───────────────────────────────────────────
        final_rows = []

        # Only consider ref_keys present in BOTH source and destination groups
        common_ref_keys = set(src_groups_meta.keys()) & set(dest_groups_meta.keys())

        for ref_key in common_ref_keys:
            s_meta = src_groups_meta[ref_key]
            d_meta = dest_groups_meta[ref_key]

            # SKIP pure 1:1 groups — those are handled by Layer 1 and Layer 2
            # We only proceed if at least one side has multiple rows
            if s_meta["count"] == 1 and d_meta["count"] == 1:
                continue

            # CHECK: summed amounts within tolerance
            # The group totals on source and destination must balance
            if abs(s_meta["sum"] - d_meta["sum"]) > self.tol_amount:
                continue

            # CHECK: representative datetimes within time tolerance
            # Compares the median datetime of src group vs median datetime of dest group
            try:
                dt_diff = abs(s_meta["repr_dt"] - d_meta["repr_dt"])
                if dt_diff > self.tol_time:
                    continue
            except Exception:
                # If datetime comparison fails (e.g. NaT), skip this pair
                continue

            # ── Step 4: Expand matched groups to row-level pairs ──────────
            # For a 2:3 match (2 src rows, 3 dest rows), this produces 2×3=6 output rows.
            # Each output row represents one src-row ↔ dest-row pairing.
            # The reconciliation UI and reports show these at row level.
            for s_row in s_meta["rows"]:
                s_dict = s_row.to_dict()

                for d_row in d_meta["rows"]:
                    d_dict = d_row.to_dict()

                    final_rows.append({
                        **{f"{k}_x": v for k, v in s_dict.items()},
                        **{f"{k}_y": v for k, v in d_dict.items()},
                    })

        return pd.DataFrame(final_rows)

    # ============================================================
    # LAYER 4 — FUZZY MATCH
    # ============================================================
    # PURPOSE:
    #   Match records where amount and datetime match (within tolerance),
    #   but reference strings are SIMILAR but not identical.
    #
    # BUSINESS CASE:
    #   - "INV-2024-001" vs "INV2024001" (different formatting)
    #   - "PAYMENT TO ACME" vs "ACME CORP PAYMENT" (word reordering)
    #   - Typos in reference numbers
    #
    # MATCH CRITERIA:
    #   - Amount: EXACT match (no tolerance here — fuzzy refs + tolerant amount = too loose)
    #   - Datetime: within tol_time
    #   - References: fuzzy similarity score >= 80/100 (RapidFuzz token_sort_ratio)
    #
    # OPTIMIZATION:
    #   - Block by exact amount first (only fuzzy-match within same amount bucket)
    #   - Time-window filter before fuzzy (reduces fuzzy candidates dramatically)
    #   - Batch processing in chunks of 10,000 for memory efficiency
    #
    # OUTPUT: DataFrame with _x/_y columns plus "score" (fuzzy similarity 0-100)
    # ============================================================
    def layer4_fuzzy(self, src: pd.DataFrame, dest: pd.DataFrame):
        logging.info(f"Layer 4 (Fuzzy) started | src: {len(src)} dest: {len(dest)}")
        src_cols = [c for c in self.src_refs if c in src.columns]
        dest_cols = [c for c in self.dest_refs if c in dest.columns]

        if not src_cols or not dest_cols:
            return pd.DataFrame()

        src_work = self._prepare_df(src, src_cols)
        dest_work = self._prepare_df(dest, dest_cols)

        if src_work.empty or dest_work.empty:
            return pd.DataFrame()

        # Concatenate all reference columns into a single string for fuzzy matching
        # e.g. ["REF001", "ACC123"] → "REF001 ACC123"
        src_work[src_cols] = src_work[src_cols].astype(str)
        dest_work[dest_cols] = dest_work[dest_cols].astype(str)

        src_work["ref"] = src_work[src_cols].agg(" ".join, axis=1)
        dest_work["ref"] = dest_work[dest_cols].agg(" ".join, axis=1)

        # Pre-group destination by EXACT amount for blocking
        # Only rows with the same amount can be fuzzy-matched (keeps results reliable)
        dest_amount_map = {}
        for amt, grp in dest_work.groupby("amount", sort=False):
            grp_sorted = grp.sort_values("datetime").reset_index(drop=True)
            dest_amount_map[amt] = grp_sorted

        matches = []

        # Process source in batches to limit memory usage
        for i in range(0, len(src_work), 10000):
            batch = src_work.iloc[i:i + 10000]

            for _, s in batch.iterrows():
                # Block: only consider dest rows with same exact amount
                candidate_dest = dest_amount_map.get(s["amount"])
                if candidate_dest is None or candidate_dest.empty:
                    continue

                # Filter by time window before fuzzy matching (cheaper operation first)
                lo = s["datetime"] - self.tol_time
                hi = s["datetime"] + self.tol_time

                cand = candidate_dest[
                    (candidate_dest["datetime"] >= lo) &
                    (candidate_dest["datetime"] <= hi)
                ]

                if cand.empty:
                    continue

                # Fuzzy match the source ref string against all candidate dest ref strings
                # extractOne returns: (best_match_str, score, index_in_cand_refs)
                cand_refs = cand["ref"].tolist()
                result = extractOne(s["ref"], cand_refs, score_cutoff=80)

                if result is None:
                    continue  # No dest ref with similarity >= 80

                match_text, score, local_idx = result
                d = cand.iloc[local_idx]

                try:
                    time_diff = abs(s["datetime"] - d["datetime"])
                    amt_diff = abs(s["amount"] - d["amount"])
                except Exception:
                    continue

                # Final validation: all criteria confirmed
                if (
                    score >= 80 and
                    amt_diff == 0 and           # exact amount match required
                    time_diff <= self.tol_time
                ):
                    matches.append({
                        **{f"{k}_x": v for k, v in s.to_dict().items()},
                        **{f"{k}_y": v for k, v in d.to_dict().items()},
                        "score": score
                    })

        return pd.DataFrame(matches)

    # ============================================================
    # LAYER 5 — LLM MATCHING
    # ============================================================
    # PURPOSE:
    #   Use a Large Language Model (LLM) as a last-resort matcher for records
    #   that no algorithmic layer could match. The LLM has context awareness
    #   and can match based on semantic similarity of references, partial
    #   matches, and complex many-to-many patterns.
    #
    # DESIGN:
    #   - Async execution with configurable concurrency (MAX_CONCURRENCY=3)
    #   - Chunked: src in batches of 40, dest in batches of 120
    #   - Retry logic: up to 2 retries per chunk on failure
    #   - Global deduplication: each row matched at most once across all chunks
    #   - Calls an external Ollama-compatible LLM API (configurable via env vars)
    #
    # ENVIRONMENT VARIABLES:
    #   LLM_URL   — API endpoint (default: Ollama endpoint at osourceglobal.com)
    #   LLM_MODEL — Model name (default: "qwen2.5:14b")
    #
    # NOTE: Layer 5 is disabled on personal PC (skip_llm=True in run_job).
    #       It requires the LLM server to be reachable.
    # ============================================================
    def layer5_llm(self, src: pd.DataFrame, dest: pd.DataFrame):
        """
        Sync wrapper around the async LLM matcher.
        Handles both standalone asyncio run and existing event loop scenarios.
        """
        try:
            return asyncio.run(self._layer5_llm_async(src, dest))
        except RuntimeError:
            # If an event loop is already running (e.g. in Jupyter/FastAPI context),
            # create a new loop in a new thread
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(self._layer5_llm_async(src, dest))
            finally:
                loop.close()

    async def _layer5_llm_async(self, src: pd.DataFrame, dest: pd.DataFrame):
        """
        Async implementation of LLM matching.
        Processes src × dest chunk combinations concurrently.
        """
        SRC_CHUNK_SIZE = 40      # rows per source chunk sent to LLM
        DEST_CHUNK_SIZE = 120    # rows per dest chunk sent to LLM
        MAX_CONCURRENCY = 3      # max simultaneous LLM API calls
        MAX_RETRIES = 2          # retry attempts per chunk on failure

        timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)

        use_src_cols = ["_ref_key", "datetime", "amount"]
        use_dest_cols = self.dest_refs + ["datetime", "amount"]

        src_work = self._prepare_df(src, self.src_refs)
        dest_work = self._prepare_df(dest, self.dest_refs)

        src_work = src_work[use_src_cols].copy()
        dest_work = dest_work[use_dest_cols].copy()

        if src_work.empty or dest_work.empty:
            logging.info("🔹 Layer5 skipped → source or destination empty after preparation")
            return pd.DataFrame()

        # Add absolute index trackers so we can deduplicate across chunk boundaries
        src_work = src_work.reset_index().rename(columns={"index": "__abs_src_idx"})
        dest_work = dest_work.reset_index().rename(columns={"index": "__abs_dest_idx"})

        logging.info(
            f"🔹 Layer5 input prepared | src_rows={len(src_work)} | dest_rows={len(dest_work)}"
        )

        # Split into chunks for API calls
        src_chunks = [
            src_work.iloc[i:i + SRC_CHUNK_SIZE].copy().reset_index(drop=True)
            for i in range(0, len(src_work), SRC_CHUNK_SIZE)
        ]

        dest_chunks = [
            dest_work.iloc[j:j + DEST_CHUNK_SIZE].copy().reset_index(drop=True)
            for j in range(0, len(dest_work), DEST_CHUNK_SIZE)
        ]

        logging.info(
            f"🔹 Layer5 chunking | src_chunks={len(src_chunks)} | dest_chunks={len(dest_chunks)} "
            f"| src_chunk_size={SRC_CHUNK_SIZE} | dest_chunk_size={DEST_CHUNK_SIZE}"
        )

        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

        # Track which absolute indices have been matched to prevent double-matching
        matched_src_abs = set()
        matched_dest_abs = set()

        accepted_output_rows = []

        async with httpx.AsyncClient(timeout=timeout) as client:
            for si, src_chunk in enumerate(src_chunks, start=1):

                # Skip source rows already matched by earlier chunks
                src_chunk_unmatched = src_chunk[~src_chunk["__abs_src_idx"].isin(matched_src_abs)].copy()
                if src_chunk_unmatched.empty:
                    logging.info(f"🔹 Layer5 src_chunk {si}/{len(src_chunks)} skipped (all source rows already matched)")
                    continue

                tasks = []

                for dj, dest_chunk in enumerate(dest_chunks, start=1):
                    dest_chunk_unmatched = dest_chunk[~dest_chunk["__abs_dest_idx"].isin(matched_dest_abs)].copy()
                    if dest_chunk_unmatched.empty:
                        continue

                    chunk_label = f"S{si}/{len(src_chunks)}-D{dj}/{len(dest_chunks)}"

                    tasks.append(
                        self._call_llm_chunk(
                            client=client,
                            semaphore=semaphore,
                            src_chunk=src_chunk_unmatched,
                            dest_chunk=dest_chunk_unmatched,
                            chunk_label=chunk_label,
                            max_retries=MAX_RETRIES,
                        )
                    )

                if not tasks:
                    continue

                # Run all dest chunks against this src chunk concurrently
                chunk_outputs = await asyncio.gather(*tasks, return_exceptions=True)

                chunk_results = []
                for item in chunk_outputs:
                    if isinstance(item, Exception):
                        logging.error(f"❌ Layer5 async chunk task failure: {item}")
                        continue
                    if item:
                        chunk_results.extend(item)

                # Deduplicate and accept valid matches
                accepted_pairs = self._accept_chunk_matches(
                    chunk_results,
                    matched_src_abs,
                    matched_dest_abs
                )

                accepted_output_rows.extend(
                    self._expand_llm_pairs_to_rows(accepted_pairs)
                )

        logging.info(
            f"✅ Layer5 final accepted matches → src_matched={len(matched_src_abs)} | "
            f"dest_matched={len(matched_dest_abs)} | output_rows={len(accepted_output_rows)}"
        )

        return pd.DataFrame(accepted_output_rows)

    async def _call_llm_chunk(self, client, semaphore, src_chunk, dest_chunk, chunk_label, max_retries=2):
        """
        Make one async LLM API call for a src_chunk × dest_chunk pair.
        Returns a list of enriched match dicts (with absolute index maps for dedup).
        """
        async with semaphore:
            start = time.time()

            # Remove internal index tracking columns before sending to LLM
            src_prompt_df = src_chunk.drop(columns=["__abs_src_idx"], errors="ignore").copy()
            dest_prompt_df = dest_chunk.drop(columns=["__abs_dest_idx"], errors="ignore").copy()

            src_json = self._make_json_safe(src_prompt_df)
            dest_json = self._make_json_safe(dest_prompt_df)

            prompt = self._build_llm_prompt(src_json, dest_json)

            logging.info(
                f"🔹 Layer5 chunk {chunk_label} started | "
                f"src_rows={len(src_prompt_df)} | dest_rows={len(dest_prompt_df)}"
            )

            attempt = 0
            while True:
                try:
                    attempt += 1

                    llm_url = os.environ.get("LLM_URL", "https://ollama.osourceglobal.com:11434/api/generate")
                    llm_model = os.environ.get("LLM_MODEL", "qwen2.5:14b")

                    res = await client.post(
                        llm_url,
                        json={
                            "model": llm_model,
                            "prompt": prompt,
                            "stream": False
                        }
                    )

                    payload = res.json()
                    raw_text = payload.get("response", "[]")
                    matches = self._parse_llm_json(raw_text)

                    elapsed = time.time() - start
                    logging.info(
                        f"✅ Layer5 chunk {chunk_label} completed | "
                        f"attempt={attempt} | llm_matches={len(matches)} | time={round(elapsed, 2)} sec"
                    )

                    # Enrich each match with absolute index maps for cross-chunk deduplication
                    src_abs_map = src_chunk["__abs_src_idx"].tolist()
                    dest_abs_map = dest_chunk["__abs_dest_idx"].tolist()

                    enriched = []
                    for m in matches:
                        enriched.append({
                            "chunk_label": chunk_label,
                            "match_type": m.get("match_type", "unknown"),
                            "source_indices": m.get("source_indices", []),
                            "dest_indices": m.get("dest_indices", []),
                            "confidence_score": m.get("confidence_score", 0.7),
                            "reason": m.get("reason", ""),
                            "src_abs_map": src_abs_map,
                            "dest_abs_map": dest_abs_map,
                            "src_chunk": src_chunk,
                            "dest_chunk": dest_chunk,
                        })

                    return enriched

                except Exception as e:
                    if attempt <= max_retries:
                        wait_secs = 1.5 * attempt
                        logging.warning(
                            f"⚠️ Layer5 chunk {chunk_label} retry {attempt}/{max_retries} "
                            f"after error: {e} | waiting {wait_secs} sec"
                        )
                        await asyncio.sleep(wait_secs)
                        continue

                    elapsed = time.time() - start
                    logging.error(
                        f"❌ Layer5 chunk {chunk_label} failed after retries | "
                        f"time={round(elapsed, 2)} sec | error={e}"
                    )
                    return []

    def _accept_chunk_matches(self, chunk_results, matched_src_abs, matched_dest_abs):
        """
        Greedy global deduplication for LLM results.

        For each candidate match returned by the LLM:
          1. Convert local chunk indices to absolute dataset indices
          2. Skip if ANY source OR destination row was already matched
          3. Accept and register the match (update matched sets)

        This ensures each row appears in at most one match across all chunks.
        """
        accepted = []

        for m in chunk_results:
            src_loc = m.get("source_indices", [])
            dest_loc = m.get("dest_indices", [])

            src_abs_map = m.get("src_abs_map", [])
            dest_abs_map = m.get("dest_abs_map", [])

            try:
                # Map local chunk indices → absolute dataset indices
                src_abs_indices = [src_abs_map[i] for i in src_loc if i < len(src_abs_map)]
                dest_abs_indices = [dest_abs_map[i] for i in dest_loc if i < len(dest_abs_map)]
            except Exception:
                continue

            if not src_abs_indices or not dest_abs_indices:
                continue

            # Reject if any row already matched
            if any(i in matched_src_abs for i in src_abs_indices):
                continue

            if any(i in matched_dest_abs for i in dest_abs_indices):
                continue

            # Accept and register
            matched_src_abs.update(src_abs_indices)
            matched_dest_abs.update(dest_abs_indices)

            accepted.append({
                "match_type": m.get("match_type", "unknown"),
                "confidence_score": m.get("confidence_score", 0.7),
                "reason": m.get("reason", ""),
                "src_abs_indices": src_abs_indices,
                "dest_abs_indices": dest_abs_indices,
                "src_chunk": m.get("src_chunk"),
                "dest_chunk": m.get("dest_chunk"),
            })

        return accepted

    def _expand_llm_pairs_to_rows(self, accepted_pairs):
        """
        Expand accepted LLM match pairs from (group → group) to (row × row) pairs.
        Each accepted pair may cover N src rows × M dest rows.
        Output is one row per src × dest combination (same structure as other layers).
        """
        rows = []

        for item in accepted_pairs:
            src_chunk = item["src_chunk"]
            dest_chunk = item["dest_chunk"]
            match_type = item["match_type"]
            score = item["confidence_score"]
            reason = item["reason"]

            src_rows = src_chunk[src_chunk["__abs_src_idx"].isin(item["src_abs_indices"])]
            dest_rows = dest_chunk[dest_chunk["__abs_dest_idx"].isin(item["dest_abs_indices"])]

            if src_rows.empty or dest_rows.empty:
                continue

            for _, s in src_rows.iterrows():
                s_dict = s.drop(labels=["__abs_src_idx"], errors="ignore").to_dict()

                for _, d in dest_rows.iterrows():
                    d_dict = d.drop(labels=["__abs_dest_idx"], errors="ignore").to_dict()

                    rows.append({
                        **{f"{k}_x": v for k, v in s_dict.items()},
                        **{f"{k}_y": v for k, v in d_dict.items()},
                        "score": score,
                        "match_type": match_type,
                        "reason": reason,
                        "index_x": s["__abs_src_idx"],
                        "index_y": d["__abs_dest_idx"],
                    })

        return rows

    # ============================================================
    # ORCHESTRATOR — run_all_layers
    # ============================================================
    # PURPOSE:
    #   Execute all matching layers in sequence (waterfall pattern).
    #   After each layer, matched rows are REMOVED from both src and dest
    #   before the next layer runs.
    #
    # WATERFALL PRINCIPLE:
    #   Layer N only sees rows that were NOT matched by Layers 0 through N-1.
    #   This guarantees:
    #     - No double-matching
    #     - Strictest match wins (layers run from most to least strict)
    #     - Each layer only processes genuinely difficult records
    #
    # PROGRESS TRACKING:
    #   Optional progress_callback receives dict payloads with:
    #     {"status": str, "progress": int 0-100, "layer": str, "count": int, ...}
    #   These are broadcast via WebSocket to the frontend live tracking view.
    #
    # PARAMETERS:
    #   src_df         — Source DataFrame with columns: record_id, datetime, amount, refs...
    #   dest_df        — Destination DataFrame with same structure
    #   progress_callback — Optional callable for WebSocket progress updates
    #   skip_llm       — If True, Layer 5 is skipped (use on personal PC without LLM server)
    #
    # RETURNS dict:
    #   {
    #     "layers": {
    #       "Self Knock": {"matches": DataFrame, "count": int, "time_sec": float},
    #       "Exact Match": {...},
    #       ...
    #     },
    #     "unmatched_src": DataFrame,   ← rows that no layer matched
    #     "unmatched_dest": DataFrame,  ← rows that no layer matched
    #     "total_matched": int,
    #   }
    # ============================================================
    def run_all_layers(
        self,
        src_df: pd.DataFrame,
        dest_df: pd.DataFrame,
        progress_callback=None,
        skip_llm: bool = False,
    ) -> dict:
        import time

        def push(msg, pct, extra=None):
            """Send progress update via WebSocket callback if registered."""
            if progress_callback:
                payload = {"status": msg, "progress": pct}
                if extra:
                    payload.update(extra)
                progress_callback(payload)

        results = {}
        src_work = src_df.copy()   # working copy — rows removed as they are matched
        dest_work = dest_df.copy() # working copy — rows removed as they are matched
        total_matched = 0

        def drop_matched_src(df, matches):
            """Remove source rows that appear in a layer's match results."""
            if matches.empty or "record_id_x" not in matches.columns:
                return df
            ids = matches["record_id_x"].dropna().tolist()
            return df[~df["record_id"].isin(ids)]

        def drop_matched_dest(df, matches):
            """Remove dest rows that appear in a layer's match results."""
            if matches.empty or "record_id_y" not in matches.columns:
                return df
            ids = matches["record_id_y"].dropna().tolist()
            return df[~df["record_id"].isin(ids)]

        # ── Layer 0: Self Knock ──────────────────────────────────────────
        # Matches internal +/- reversals within source AND within destination.
        # These rows are excluded from all cross-side matching layers.
        push("Running Layer 0: Self Knock...", 10)
        t0 = time.time()
        l0_src = self.layer0_self_knock(src_work)
        l0_dest = self.layer0_self_knock_dest(dest_work)
        l0_combined = pd.concat([l0_src, l0_dest], ignore_index=True)
        t0_time = round(time.time() - t0, 2)
        count0 = len(l0_src) + len(l0_dest)
        results["Self Knock"] = {"matches": l0_combined, "raw_src": l0_src, "raw_dest": l0_dest, "count": count0, "time_sec": t0_time}
        # Remove self-knocked rows from working sets
        if not l0_src.empty and "record_id" in l0_src.columns:
            src_work = src_work[~src_work["record_id"].isin(l0_src["record_id"].tolist())]
        if not l0_dest.empty and "record_id" in l0_dest.columns:
            dest_work = dest_work[~dest_work["record_id"].isin(l0_dest["record_id"].tolist())]
        total_matched += count0
        push("Layer 0 done", 18, {"layer": "Self Knock", "count": count0, "time_sec": t0_time})

        # ── Layer 1: Exact Match ─────────────────────────────────────────
        # Strictest cross-side match: refs + datetime + amount all identical.
        push("Running Layer 1: Exact Match...", 25)
        t1 = time.time()
        l1 = self.layer1_exact(src_work, dest_work)
        t1_time = round(time.time() - t1, 2)
        count1 = len(l1)
        results["Exact Match"] = {"matches": l1, "count": count1, "time_sec": t1_time}
        src_work = drop_matched_src(src_work, l1)
        dest_work = drop_matched_dest(dest_work, l1)
        total_matched += count1
        push("Layer 1 done", 35, {"layer": "Exact Match", "count": count1, "time_sec": t1_time})

        # ── Layer 2: Tolerance Match ─────────────────────────────────────
        # Exact refs, but amount and/or datetime within configured tolerance bands.
        push("Running Layer 2: Tolerance Match...", 42)
        t2 = time.time()
        l2 = self.layer2_tolerance(src_work, dest_work)
        t2_time = round(time.time() - t2, 2)
        count2 = len(l2)
        results["Tolerance Match"] = {"matches": l2, "count": count2, "time_sec": t2_time}
        src_work = drop_matched_src(src_work, l2)
        dest_work = drop_matched_dest(dest_work, l2)
        total_matched += count2
        push("Layer 2 done", 52, {"layer": "Tolerance Match", "count": count2, "time_sec": t2_time})

        # ── Layer 3: N:M Subset / Group Match ───────────────────────────
        # Many-to-many grouped matching: groups of rows with same refs whose
        # SUMMED amounts match. Covers 1:N, N:1, and N:M patterns.
        # 1:1 pairs are explicitly skipped (handled by Layer 1/2 above).
        push("Running Layer 3: N:M Subset Match...", 58)
        t3 = time.time()
        l3 = self.layer3_subset(src_work, dest_work)
        t3_time = round(time.time() - t3, 2)
        count3 = len(l3)
        results["Subset Match"] = {"matches": l3, "count": count3, "time_sec": t3_time}
        src_work = drop_matched_src(src_work, l3)
        dest_work = drop_matched_dest(dest_work, l3)
        total_matched += count3
        push("Layer 3 done", 68, {"layer": "Subset Match", "count": count3, "time_sec": t3_time})

        # ── Layer 4: Fuzzy Match ─────────────────────────────────────────
        # Same amount (exact), datetime within tolerance, but references
        # are only SIMILAR (fuzzy scored >= 80/100) rather than exact.
        push("Running Layer 4: Fuzzy Match...", 74)
        t4 = time.time()
        l4 = self.layer4_fuzzy(src_work, dest_work)
        t4_time = round(time.time() - t4, 2)
        count4 = len(l4)
        results["Fuzzy Match"] = {"matches": l4, "count": count4, "time_sec": t4_time}
        src_work = drop_matched_src(src_work, l4)
        dest_work = drop_matched_dest(dest_work, l4)
        total_matched += count4
        push("Layer 4 done", 83, {"layer": "Fuzzy Match", "count": count4, "time_sec": t4_time})

        # ── Layer 5: LLM Match ───────────────────────────────────────────
        # AI-powered matching for genuinely complex remaining records.
        # Disabled on personal PC (skip_llm=True) — requires LLM API server.
        count5, t5_time = 0, 0.0
        if not skip_llm:
            push("Running Layer 5: LLM Match...", 88)
            t5 = time.time()
            try:
                l5 = self.layer5_llm(src_work, dest_work)
                t5_time = round(time.time() - t5, 2)
                count5 = len(l5)
                results["LLM Match"] = {"matches": l5, "count": count5, "time_sec": t5_time}
                src_work = drop_matched_src(src_work, l5)
                dest_work = drop_matched_dest(dest_work, l5)
                total_matched += count5
            except Exception as e:
                logging.warning(f"Layer 5 (LLM) skipped: {e}")
                results["LLM Match"] = {"matches": pd.DataFrame(), "count": 0, "time_sec": 0.0}
            push("Layer 5 done", 95, {"layer": "LLM Match", "count": count5, "time_sec": t5_time})
        else:
            logging.info("Layer 5 (LLM) skipped — skip_llm=True")
            results["LLM Match"] = {"matches": pd.DataFrame(), "count": 0, "time_sec": 0.0}

        push("Reconciliation complete!", 100)

        return {
            "layers": results,
            "unmatched_src": src_work,    # rows from source with no match found
            "unmatched_dest": dest_work,  # rows from dest with no match found
            "total_matched": total_matched,
        }