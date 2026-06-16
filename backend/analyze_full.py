import pandas as pd
import sys
import os

sys.path.append(r"d:\Library\Documents\Projects\Internship\Recon\backend")
from matching_engine import MatchingEngine

src_file = r"d:\Library\Documents\Projects\Internship\Recon\uploads\JW Marriott Prestige Golfshire Resort_Source.xlsx"
dest_file = r"d:\Library\Documents\Projects\Internship\Recon\uploads\JW Marriott Prestige Golfshire Resort_Destination.xlsx"

src_df = pd.read_excel(src_file)
dest_df = pd.read_excel(dest_file)

src_df['datetime'] = pd.to_datetime(src_df['Modified_DateTime'], errors='coerce')
src_df['amount'] = pd.to_numeric(src_df['CASHIER_CREDIT'], errors='coerce').fillna(0)
src_df['ref_1'] = src_df['CC_type'].astype(str)
src_df['ref_2'] = src_df['Modified_Card'].astype(str)
src_df['ref_3'] = src_df['Outlet'].astype(str)

dest_df['datetime'] = pd.to_datetime(dest_df['Transaction Timestamp'], errors='coerce')
dest_df['amount'] = pd.to_numeric(dest_df['Charge Amount'], errors='coerce').fillna(0)
dest_df['ref_1'] = dest_df['CC_type'].astype(str)
dest_df['ref_2'] = dest_df['Modified_Card'].astype(str)
dest_df['ref_3'] = dest_df['Outlet'].astype(str)

for df in [src_df, dest_df]:
    df['row_id'] = range(len(df))

mapping = {
    "source": {"references": ["ref_1", "ref_2", "ref_3"]},
    "dest": {"references": ["ref_1", "ref_2", "ref_3"]}
}
engine = MatchingEngine(tol_amount=10, tol_time=10, mapping=mapping) # 10 mins

print("Running full ReconciliationEngine pipeline...")
result = engine.run_all_layers(src_df, dest_df, skip_llm=True)

print("\n--- RESULTS ---")
for layer, data in result['layers'].items():
    print(f"{layer}: {data['count']} matches")

