import re

with open("matching_engine.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Update _prepare_df to create _ref_key
code = code.replace(
    '''        # Ensure amount is numeric (handles strings like "1,234.56")
        if "amount" in df.columns:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce")''',
    '''        # Ensure amount is numeric (handles strings like "1,234.56")
        if "amount" in df.columns:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

        # Create order-independent composite reference key
        # We sort the values so that column selection order doesn't matter.
        df["_ref_key"] = df[ref_cols].apply(
            lambda row: tuple(sorted([str(v).strip().upper() for c, v in row.items() if c in ref_cols and pd.notna(v) and str(v).strip() != ""])),
            axis=1
        )'''
)

# 2. Make _rename_dest_refs a no-op
code = re.sub(
    r'    def _rename_dest_refs\(self, dest: pd.DataFrame\) -> pd.DataFrame:\n.*?(?=\n    def _make_json_safe)',
    '''    def _rename_dest_refs(self, dest: pd.DataFrame) -> pd.DataFrame:
        # No longer needed since we use order-independent _ref_key
        return dest''',
    code,
    flags=re.DOTALL
)

# 3. Replace groupby keys
code = code.replace('group_cols = self.src_refs + ["datetime"]', 'group_cols = ["_ref_key", "datetime"]')
code = code.replace('cols = self.src_refs + ["datetime", "amount"]', 'cols = ["_ref_key", "datetime", "amount"]')
code = code.replace('dest_work.groupby(self.src_refs, observed=True, sort=False)', 'dest_work.groupby(["_ref_key"], observed=True, sort=False)')
code = code.replace('src_work.groupby(self.src_refs, observed=True, sort=False)', 'src_work.groupby(["_ref_key"], observed=True, sort=False)')
code = code.replace('cols = self.src_refs   # Reference columns used as group key', 'cols = ["_ref_key"]')
code = code.replace('use_src_cols = self.src_refs + ["datetime", "amount"]', 'use_src_cols = ["_ref_key", "datetime", "amount"]')

# 4. Layer 4 Fuzzy uses src_cols
code = code.replace(
    '''        src_cols = [c for c in self.src_refs if c in src.columns]
        dest_cols = [c for c in self.src_refs if c in dest.columns]

        def get_concat_str(row, cols):
            return " ".join(str(row[c]) for c in cols if pd.notna(row[c])).upper()

        src_work["_fuzzy_str"] = src_work.apply(lambda r: get_concat_str(r, src_cols), axis=1)
        dest_work["_fuzzy_str"] = dest_work.apply(lambda r: get_concat_str(r, dest_cols), axis=1)''',
    '''        src_work["_fuzzy_str"] = src_work["_ref_key"].apply(lambda t: " ".join(t))
        dest_work["_fuzzy_str"] = dest_work["_ref_key"].apply(lambda t: " ".join(t))'''
)

with open("matching_engine.py", "w", encoding="utf-8") as f:
    f.write(code)

print("matching_engine.py patched!")
