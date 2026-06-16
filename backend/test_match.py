import sys
import os
import pandas as pd

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from parsers import read_any_file
from utils import clean_mapped_dataframe
from matching_engine import MatchingEngine

def run_test():
    src_path = r"../uploads/Many_source_Template (1).xlsx"
    dest_path = r"../uploads/manytomany_dest_Template (1).xlsx"

    mapping = {
        "source": {
            "datetime": "Modified_DateTime",
            "amount": "CASHIER_CREDIT",
            "references": ["CREDIT_CARD_SUPPLEMENT", "Modified_Card"]
        },
        "dest": {
            "datetime": "Modified_DateTime",
            "amount": "Value_of_Sale",
            "references": ["Transaction_Description", "Modified_Card"]
        }
    }

    print("Reading Source...")
    src_raw = read_any_file(src_path)
    print("Reading Dest...")
    dest_raw = read_any_file(dest_path)

    print("Cleaning Source...")
    src_records = clean_mapped_dataframe(src_raw, mapping, "source")
    print("Cleaning Dest...")
    dest_records = clean_mapped_dataframe(dest_raw, mapping, "dest")

    def recs_to_df(records):
        rows = []
        for i, r in enumerate(records):
            row = {
                "record_id": i,
                "datetime": r["txn_datetime"],
                "amount": r["amount"],
                **r["references"],
            }
            rows.append(row)
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    src_df = recs_to_df(src_records)
    dest_df = recs_to_df(dest_records)

    with open("logs.txt", "w") as f:
        f.write("=== SOURCE DATAFRAME ===\n")
        f.write(src_df.to_string() + "\n\n")
        f.write("=== DEST DATAFRAME ===\n")
        f.write(dest_df.to_string() + "\n\n")

    print(f"Source cleaned size: {len(src_df)}, Dest cleaned size: {len(dest_df)}")

    engine_mapping = {
        "source": {"references": mapping["source"]["references"]},
        "dest": {"references": mapping["dest"]["references"]}
    }

    engine = MatchingEngine(tol_amount=10, tol_time=10, mapping=engine_mapping)

    l0 = engine.layer0_self_knock(src_df)
    print(f"L0 Self Knock: {len(l0)}")
    if not l0.empty: src_df = src_df.drop(l0.index)
        
    l1 = engine.layer1_exact(src_df, dest_df)
    print(f"L1 Exact Matches: {len(l1)}")

    l2 = engine.layer2_tolerance(src_df, dest_df)
    print(f"L2 Tolerance Matches: {len(l2)}")

    l3 = engine.layer3_subset(src_df, dest_df)
    print(f"L3 Subset Matches: {len(l3)}")

    l4 = engine.layer4_fuzzy(src_df, dest_df)
    print(f"L4 Fuzzy Matches: {len(l4)}")

if __name__ == "__main__":
    run_test()
