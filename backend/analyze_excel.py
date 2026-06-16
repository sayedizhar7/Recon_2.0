import pandas as pd
import numpy as np

src_file = r"d:\Library\Documents\Projects\Internship\Recon\uploads\Many_source_Template (1).xlsx"
dest_file = r"d:\Library\Documents\Projects\Internship\Recon\uploads\manytomany_dest_Template (1).xlsx"

src_df = pd.read_excel(src_file)
dest_df = pd.read_excel(dest_file)

src_df['datetime'] = pd.to_datetime(src_df['Modified_DateTime'], errors='coerce')
src_df['amount'] = pd.to_numeric(src_df['CASHIER_CREDIT'], errors='coerce').fillna(0)
src_df['ref_Modified_Card'] = src_df['Modified_Card'].astype(str)

dest_df['datetime'] = pd.to_datetime(dest_df['Modified_DateTime'], errors='coerce')
dest_df['amount'] = pd.to_numeric(dest_df['Net Amount'], errors='coerce').fillna(0)
dest_df['ref_Modified_Card'] = dest_df['Modified_Card'].astype(str)

for df in [src_df, dest_df]:
    df['row_id'] = range(len(df))

tol_amount = 10
tol_time = pd.Timedelta(minutes=10)
references = ['ref_Modified_Card']

print("Running Layer 3 Subset logic...")

def analyze_layer3(src_df, dest_df):
    ref_cols = references
    src_groups_meta = {}
    for ref_key, grp in src_df.groupby(ref_cols):
        rows_list = [row for _, row in grp.iterrows()]
        src_groups_meta[ref_key] = {
            "sum": float(grp["amount"].sum()),
            "count": len(rows_list),
            "repr_dt": grp["datetime"].sort_values().iloc[len(grp) // 2],
        }
    
    dest_groups_meta = {}
    for ref_key, grp in dest_df.groupby(ref_cols):
        rows_list = [row for _, row in grp.iterrows()]
        dest_groups_meta[ref_key] = {
            "sum": float(grp["amount"].sum()),
            "count": len(rows_list),
            "repr_dt": grp["datetime"].sort_values().iloc[len(grp) // 2],
        }
        
    common_keys = set(src_groups_meta.keys()) & set(dest_groups_meta.keys())
    print(f"Common Reference Keys: {len(common_keys)}")
    
    matched_pairs = 0
    for k in common_keys:
        s_meta = src_groups_meta[k]
        d_meta = dest_groups_meta[k]
        
        print(f"\nKey: {k}")
        print(f"  Src: sum={s_meta['sum']:.2f}, count={s_meta['count']}, dt={s_meta['repr_dt']}")
        print(f"  Dst: sum={d_meta['sum']:.2f}, count={d_meta['count']}, dt={d_meta['repr_dt']}")
        
        if s_meta["count"] == 1 and d_meta["count"] == 1:
            print("  -> SKIPPED (1:1 group)")
            continue
            
        if abs(s_meta["sum"] - d_meta["sum"]) > 10:
            print(f"  -> SKIPPED (Sum mismatch: {s_meta['sum']:.2f} vs {d_meta['sum']:.2f})")
            continue
            
        try:
            dt_diff = abs(s_meta["repr_dt"] - d_meta["repr_dt"])
            if dt_diff > tol_time:
                print(f"  -> SKIPPED (Time mismatch: {dt_diff})")
                continue
        except:
            print("  -> SKIPPED (Time compare failed, maybe NaT)")
            continue
            
        matches = s_meta["count"] * d_meta["count"]
        print(f"  -> MATCHED! Produces {matches} pairs")
        matched_pairs += matches
        
    print(f"\nTotal matches from Layer 3: {matched_pairs}")

analyze_layer3(src_df, dest_df)
