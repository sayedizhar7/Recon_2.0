import io
import json
import logging
import os
import time
import uuid
import asyncio
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from database import (
    init_db, SessionLocal,
    UploadedFile, UnreconciledRecord, HistoryTable,
    ReconciledRecord, ExcludeRecord
)
from parsers import read_any_file
from utils import clean_mapped_dataframe
from matching_engine import MatchingEngine

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Paths — uploads and downloads at project root
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)          # project root

UPLOAD_DIR = os.path.join(ROOT_DIR, "uploads")
DOWNLOAD_DIR = os.path.join(ROOT_DIR, "downloads")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Recon 2.0 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket Manager
# ─────────────────────────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, job_id: str):
        await websocket.accept()
        self.active_connections.setdefault(job_id, []).append(websocket)

    def disconnect(self, websocket: WebSocket, job_id: str):
        if job_id in self.active_connections:
            try:
                self.active_connections[job_id].remove(websocket)
            except ValueError:
                pass
            if not self.active_connections[job_id]:
                del self.active_connections[job_id]

    async def broadcast(self, job_id: str, message: dict):
        dead = []
        for ws in self.active_connections.get(job_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, job_id)


manager = ConnectionManager()
main_loop = None


@app.on_event("startup")
def startup_event():
    global main_loop
    try:
        main_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Helper: push progress via WebSocket from a thread
# ─────────────────────────────────────────────────────────────────────────────
def push_progress(job_id: str, payload: dict):
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(manager.broadcast(job_id, payload), main_loop)


# ─────────────────────────────────────────────────────────────────────────────
# Helper: build DataFrames from DB records
# ─────────────────────────────────────────────────────────────────────────────
def records_to_df(records):
    rows = []
    for r in records:
        row = {
            "record_id": r.id,
            "datetime": r.txn_datetime,
            "amount": float(r.amount) if r.amount is not None else None,
            **r.references,
        }
        rows.append(row)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Helper: export to Excel
# ─────────────────────────────────────────────────────────────────────────────
def export_to_excel(run_id: int, matched_records: list[ReconciledRecord], db) -> str:
    rows = []
    for m in matched_records:
        row = {
            "Run ID": run_id,
            "Layer Matched": m.layer_matched,
            "Match Type": m.match_type or "",
            "Source Datetime": m.source_datetime,
            "Dest Datetime": m.dest_datetime,
            "Source Amount": float(m.source_amount) if m.source_amount else None,
            "Dest Amount": float(m.dest_amount) if m.dest_amount else None,
            "Confidence Score": float(m.confidence_score) if m.confidence_score else None,
            "Reason": m.reason or "",
        }
        # Flatten source refs
        if m.source_refs:
            for k, v in m.source_refs.items():
                row[f"Source_{k}"] = v
        # Flatten dest refs
        if m.dest_refs:
            for k, v in m.dest_refs.items():
                row[f"Dest_{k}"] = v
        rows.append(row)

    df = pd.DataFrame(rows)
    filename = f"reconciled_run_{run_id}.xlsx"
    path = os.path.join(DOWNLOAD_DIR, filename)
    df.to_excel(path, index=False)
    logger.info(f"Excel exported: {path}")
    return path


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT: Upload files → return columns
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/upload")
async def upload(source: UploadFile = File(...), dest: UploadFile = File(...)):
    db = SessionLocal()
    try:
        def save_file(file: UploadFile, side: str):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = file.filename.replace(" ", "_")
            filename = f"{side}_{ts}_{safe_name}"
            path = os.path.join(UPLOAD_DIR, filename)

            content = file.file.read()
            with open(path, "wb") as f:
                f.write(content)

            logger.info(f"[upload] Saved {side} file: {filename}")
            t0 = time.time()
            sample_df = read_any_file(path, nrows=50)
            logger.info(f"[upload] Column detection took {round(time.time()-t0,2)}s | cols: {sample_df.columns.tolist()}")

            rec = UploadedFile(
                side=side,
                filename=file.filename,
                file_type=os.path.splitext(file.filename)[1].lower(),
                temp_path=path,
                detected_columns=sample_df.columns.tolist(),
                status="uploaded",
            )
            db.add(rec)
            db.commit()
            db.refresh(rec)

            return {
                "upload_id": rec.id,
                "columns": sample_df.columns.tolist(),
                "path": path,
            }

        src_info = save_file(source, "source")
        dest_info = save_file(dest, "dest")

        return {
            "source_upload_id": src_info["upload_id"],
            "dest_upload_id": dest_info["upload_id"],
            "source_columns": src_info["columns"],
            "dest_columns": dest_info["columns"],
        }
    except Exception as e:
        logger.error(f"[upload] Error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT: Ingest mapped data into DB
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/ingest-mapped")
def ingest_mapped(
    source_upload_id: int = Form(...),
    dest_upload_id: int = Form(...),
    mapping: str = Form(...),
    client_id: str = Form(None),
):
    db = SessionLocal()
    try:
        mapping_dict = json.loads(mapping)
        prog = lambda msg, pct: push_progress(client_id, {"status": msg, "progress": pct}) if client_id else None

        def ingest_one(upload_id: int, side: str):
            upload_rec = db.query(UploadedFile).filter(UploadedFile.id == upload_id).first()
            if not upload_rec:
                raise Exception(f"Upload {upload_id} not found")

            t0 = time.time()
            if prog: prog(f"Reading {side} file...", 5 if side == "source" else 55)
            df = read_any_file(upload_rec.temp_path)
            logger.info(f"[ingest] {side} full read: {len(df)} rows in {round(time.time()-t0,2)}s")

            records = clean_mapped_dataframe(df, mapping_dict, side, progress_cb=prog)
            logger.info(f"[ingest] {side} cleaned: {len(records)} records")

            # ── IDEMPOTENCY FIX ────────────────────────────────────────────────
            # Delete any existing UnreconciledRecord rows for this upload_id before
            # inserting new ones. This prevents row accumulation across multiple
            # ingest calls (e.g. on "Edit & Rerun" or repeated runs with same files).
            #
            # WITHOUT this fix:
            #   1st ingest → 37 rows inserted
            #   2nd ingest → 37 more rows appended → 74 total (2× the data)
            #   Matching engine gets 74 rows → produces ~2× the matches → wrong output
            #
            # WITH this fix:
            #   1st ingest → 37 rows inserted
            #   2nd ingest → 37 old rows deleted, 37 new rows inserted → still 37 total
            #   Output is consistent regardless of how many times ingest is called.
            existing_count = db.query(UnreconciledRecord).filter(
                UnreconciledRecord.upload_id == upload_id,
                UnreconciledRecord.side == side,
            ).delete(synchronize_session=False)
            db.commit()
            if existing_count > 0:
                logger.info(f"[ingest] {side} cleared {existing_count} stale rows for upload_id={upload_id}")
            # ──────────────────────────────────────────────────────────────────

            db_rows = []
            for rec in records:
                db_rows.append(UnreconciledRecord(
                    upload_id=upload_id,
                    side=side,
                    txn_datetime=rec["txn_datetime"],
                    amount=rec["amount"],
                    references=rec["references"],
                    remaining_columns=rec["remaining_columns"],
                    checksum=rec["checksum"],
                    source_row_num=rec["source_row_num"],
                ))

            db.bulk_save_objects(db_rows)
            upload_rec.status = "mapped"
            upload_rec.row_count = len(db_rows)
            db.commit()
            logger.info(f"[ingest] {side} inserted {len(db_rows)} records")

            with open("logs.txt", "a") as f:
                f.write(f"\n\n=== {side.upper()} DATAFRAME ===\n")
                f.write(pd.DataFrame(records).to_string() + "\n")

        # Clear logs.txt
        with open("logs.txt", "w") as f:
            f.write(f"--- Ingestion Mapped Data at {datetime.now()} ---\n")

        ingest_one(source_upload_id, "source")
        ingest_one(dest_upload_id, "dest")

        return {"status": "mapped"}
    except Exception as e:
        logger.error(f"[ingest-mapped] Error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Background reconciliation job
# ─────────────────────────────────────────────────────────────────────────────
def run_reconciliation_from_db(
    run_id: int,
    source_upload_id: int,
    dest_upload_id: int,
    mapping_dict: dict,
    tol_amount: float,
    tol_time: int,
):
    db = SessionLocal()
    job_start = time.time()

    try:
        def push(payload: dict):
            push_progress(str(run_id), payload)

        push({"status": "Fetching data from database...", "progress": 5})

        src_records = db.query(UnreconciledRecord).filter(
            UnreconciledRecord.upload_id == source_upload_id,
            UnreconciledRecord.side == "source",
        ).all()

        dest_records = db.query(UnreconciledRecord).filter(
            UnreconciledRecord.upload_id == dest_upload_id,
            UnreconciledRecord.side == "dest",
        ).all()

        src_df = records_to_df(src_records)
        dest_df = records_to_df(dest_records)

        total_src = len(src_df)
        total_dest = len(dest_df)

        logger.info(f"[run {run_id}] Source rows: {total_src} | Dest rows: {total_dest}")
        push({"status": f"Loaded {total_src} source + {total_dest} dest records", "progress": 8,
              "total_source": total_src, "total_dest": total_dest})

        if src_df.empty or dest_df.empty:
            push({"status": "No data to reconcile.", "progress": 100})
            run = db.query(HistoryTable).filter(HistoryTable.id == run_id).first()
            if run:
                run.status = "completed"
                db.commit()
            return

        engine = MatchingEngine(tol_amount, tol_time, mapping_dict)

        layer_name_map = {
            "Self Knock": ("layer0_count", "layer0_time_sec"),
            "Exact Match": ("layer1_count", "layer1_time_sec"),
            "Tolerance Match": ("layer2_count", "layer2_time_sec"),
            "Subset Match": ("layer3_count", "layer3_time_sec"),
            "Fuzzy Match": ("layer4_count", "layer4_time_sec"),
            "LLM Match": ("layer5_count", "layer5_time_sec"),
        }

        conf_map = {
            "Self Knock": 1.0,
            "Exact Match": 1.0,
            "Tolerance Match": 0.95,
            "Subset Match": 0.90,
            "Fuzzy Match": 0.85,
            "LLM Match": 0.80,
        }

        # Build record_id → UnreconciledRecord lookup
        src_lookup = {r.id: r for r in src_records}
        dest_lookup = {r.id: r for r in dest_records}

        result = engine.run_all_layers(
            src_df, dest_df,
            progress_callback=push,
            skip_llm=True,   # LLM disabled on personal PC
        )

        push({"status": "Saving matches to database...", "progress": 96})

        matched_db_rows = []
        layer_counts = {}
        layer_times = {}

        for layer_name, layer_data in result["layers"].items():
            matches = layer_data["matches"]
            count = layer_data["count"]
            t_sec = layer_data["time_sec"]
            conf = conf_map.get(layer_name, 0.80)

            layer_counts[layer_name] = count
            layer_times[layer_name] = t_sec

            if matches is None or matches.empty:
                continue

            # Self Knock: rows self-knocked (no paired record_id)
            if layer_name == "Self Knock":
                for _, row in matches.iterrows():
                    rid = row.get("record_id")
                    src_rec = src_lookup.get(rid) or dest_lookup.get(rid)
                    matched_db_rows.append(ReconciledRecord(
                        run_id=run_id,
                        layer_matched=layer_name,
                        match_type="self-knock",
                        source_record_id=rid,
                        source_datetime=src_rec.txn_datetime if src_rec else None,
                        source_amount=src_rec.amount if src_rec else None,
                        source_refs=src_rec.references if src_rec else None,
                        dest_record_id=None,
                        confidence_score=conf,
                        reason="Self knock: positive + negative with same refs and datetime",
                    ))
                continue

            for _, row in matches.iterrows():
                src_id = row.get("record_id_x")
                dest_id = row.get("record_id_y")
                src_rec = src_lookup.get(src_id)
                dest_rec = dest_lookup.get(dest_id)

                matched_db_rows.append(ReconciledRecord(
                    run_id=run_id,
                    layer_matched=layer_name,
                    match_type=row.get("match_type", "one-to-one"),
                    source_record_id=src_id,
                    source_datetime=src_rec.txn_datetime if src_rec else None,
                    source_amount=src_rec.amount if src_rec else None,
                    source_refs=src_rec.references if src_rec else None,
                    dest_record_id=dest_id,
                    dest_datetime=dest_rec.txn_datetime if dest_rec else None,
                    dest_amount=dest_rec.amount if dest_rec else None,
                    dest_refs=dest_rec.references if dest_rec else None,
                    confidence_score=row.get("score", conf) if "score" in row.index else conf,
                    reason=row.get("reason", ""),
                ))

        db.bulk_save_objects(matched_db_rows)
        db.flush()

        # Excel export
        excel_path = None
        try:
            excel_path = export_to_excel(run_id, matched_db_rows, db)
        except Exception as ex:
            logger.warning(f"[run {run_id}] Excel export failed: {ex}")

        # Update history record
        total_matched = result["total_matched"]
        total_unmatched = len(result["unmatched_src"]) + len(result["unmatched_dest"])
        total_duration = round(time.time() - job_start, 2)

        run = db.query(HistoryTable).filter(HistoryTable.id == run_id).first()
        if run:
            run.status = "completed"
            run.total_source = total_src
            run.total_dest = total_dest
            run.total_matched = total_matched
            run.total_unmatched = total_unmatched
            run.layer0_count = layer_counts.get("Self Knock", 0)
            run.layer1_count = layer_counts.get("Exact Match", 0)
            run.layer2_count = layer_counts.get("Tolerance Match", 0)
            run.layer3_count = layer_counts.get("Subset Match", 0)
            run.layer4_count = layer_counts.get("Fuzzy Match", 0)
            run.layer5_count = layer_counts.get("LLM Match", 0)
            run.layer0_time_sec = layer_times.get("Self Knock", 0.0)
            run.layer1_time_sec = layer_times.get("Exact Match", 0.0)
            run.layer2_time_sec = layer_times.get("Tolerance Match", 0.0)
            run.layer3_time_sec = layer_times.get("Subset Match", 0.0)
            run.layer4_time_sec = layer_times.get("Fuzzy Match", 0.0)
            run.layer5_time_sec = layer_times.get("LLM Match", 0.0)
            run.total_duration_sec = total_duration
            run.excel_path = excel_path
            run.completed_at = datetime.utcnow()

        db.commit()

        push({
            "status": "Reconciliation completed successfully!",
            "progress": 100,
            "total_matched": total_matched,
            "total_unmatched": total_unmatched,
            "layer_counts": layer_counts,
            "layer_times": layer_times,
            "duration_sec": total_duration,
        })

        logger.info(f"[run {run_id}] Done in {total_duration}s | matched={total_matched}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        push_progress(str(run_id), {"status": f"Error: {str(e)}", "progress": -1})
        run = db.query(HistoryTable).filter(HistoryTable.id == run_id).first()
        if run:
            run.status = "failed"
            db.commit()
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT: Start async reconciliation
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/reconcile_async")
def reconcile_async(
    background_tasks: BackgroundTasks,
    source_upload_id: int = Form(...),
    dest_upload_id: int = Form(...),
    mapping: str = Form(...),
    tol_amount: float = Form(...),
    tol_time: int = Form(...),
):
    db = SessionLocal()
    try:
        mapping_dict = json.loads(mapping)

        src_rec = db.query(UploadedFile).filter(UploadedFile.id == source_upload_id).first()
        dest_rec = db.query(UploadedFile).filter(UploadedFile.id == dest_upload_id).first()

        run = HistoryTable(
            source_upload_id=source_upload_id,
            dest_upload_id=dest_upload_id,
            source_filename=src_rec.filename if src_rec else None,
            dest_filename=dest_rec.filename if dest_rec else None,
            tol_amount=tol_amount,
            tol_time_minutes=tol_time,
            date_mode=mapping_dict.get("date_mode", "datetime"),
            date_format=mapping_dict.get("date_format"),
            date_format_source=mapping_dict.get("source", {}).get("date_format"),
            date_format_dest=mapping_dict.get("dest", {}).get("date_format"),
            status="running",
            mapping_json=mapping_dict,

        )
        db.add(run)
        db.commit()
        db.refresh(run)

        background_tasks.add_task(
            run_reconciliation_from_db,
            run.id,
            source_upload_id,
            dest_upload_id,
            mapping_dict,
            tol_amount,
            tol_time,
        )

        return {"job_id": str(run.id)}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT: Test reconciliation (no DB write)
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/test-reconcile")
async def test_reconcile(
    source: UploadFile = File(...),
    dest: UploadFile = File(...),
    mapping: str = Form(...),
    tol_amount: float = Form(...),
    tol_time: int = Form(...),
    client_id: str = Form(None),
):
    try:
        mapping_dict = json.loads(mapping)
        src_filename = source.filename
        dest_filename = dest.filename

        def run_heavy_lifting(src_bytes, dest_bytes, mapping_dict, tol_amount, tol_time, client_id):
            def parse_bytes(filename, content):
                ext = os.path.splitext(filename)[1].lower()
                tmp_path = os.path.join(UPLOAD_DIR, f"test_{uuid.uuid4().hex}{ext}")
                with open(tmp_path, "wb") as f:
                    f.write(content)
                try:
                    df = read_any_file(tmp_path)
                finally:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                return df

            prog = lambda msg, pct: push_progress(client_id, {"status": msg, "progress": pct}) if client_id else None

            if prog: prog("Parsing source file...", 5)
            src_df_raw = parse_bytes(src_filename, src_bytes)
            
            if prog: prog("Parsing destination file...", 10)
            dest_df_raw = parse_bytes(dest_filename, dest_bytes)

            src_records = clean_mapped_dataframe(src_df_raw, mapping_dict, "source", progress_cb=prog)
            dest_records = clean_mapped_dataframe(dest_df_raw, mapping_dict, "dest", progress_cb=prog)

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

            if prog: prog("Preparing engine...", 35)
            src_df = recs_to_df(src_records)
            dest_df = recs_to_df(dest_records)

            engine = MatchingEngine(tol_amount, tol_time, mapping_dict)
            
            cb = lambda payload: push_progress(client_id, payload) if client_id else None
            result = engine.run_all_layers(src_df, dest_df, skip_llm=True, progress_callback=cb)

            summary = {
                "total_source": len(src_df),
                "total_dest": len(dest_df),
                "total_matched": result["total_matched"],
                "total_unmatched_src": len(result["unmatched_src"]),
                "total_unmatched_dest": len(result["unmatched_dest"]),
                "layers": {
                    name: {"count": data["count"], "time_sec": data["time_sec"]}
                    for name, data in result["layers"].items()
                },
            }
            return summary

        src_content = await source.read()
        dest_content = await dest.read()

        summary = await asyncio.to_thread(
            run_heavy_lifting, src_content, dest_content, mapping_dict, tol_amount, tol_time, client_id
        )

        return summary

    except Exception as e:
        logger.error(f"[test-reconcile] Error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT: List all runs (history)
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/runs")
def list_runs():
    db = SessionLocal()
    try:
        runs = db.query(HistoryTable).order_by(HistoryTable.id.desc()).all()
        result = []
        for r in runs:
            result.append({
                "id": r.id,
                "source_filename": r.source_filename,
                "dest_filename": r.dest_filename,
                "status": r.status,
                "source_upload_id": r.source_upload_id,
                "dest_upload_id": r.dest_upload_id,
                "mapping_json": r.mapping_json,
                "tol_amount": float(r.tol_amount) if r.tol_amount else 0,
                "tol_time_minutes": r.tol_time_minutes,
                "date_mode": r.date_mode,
                "total_source": r.total_source or 0,
                "total_dest": r.total_dest or 0,
                "total_matched": r.total_matched or 0,
                "total_unmatched": r.total_unmatched or 0,
                "layer0_count": r.layer0_count or 0,
                "layer1_count": r.layer1_count or 0,
                "layer2_count": r.layer2_count or 0,
                "layer3_count": r.layer3_count or 0,
                "layer4_count": r.layer4_count or 0,
                "layer5_count": r.layer5_count or 0,
                "layer0_time_sec": r.layer0_time_sec or 0,
                "layer1_time_sec": r.layer1_time_sec or 0,
                "layer2_time_sec": r.layer2_time_sec or 0,
                "layer3_time_sec": r.layer3_time_sec or 0,
                "layer4_time_sec": r.layer4_time_sec or 0,
                "layer5_time_sec": r.layer5_time_sec or 0,
                "total_duration_sec": r.total_duration_sec or 0,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            })
        return result
    finally:
        db.close()


@app.get("/uploads/{upload_id}/columns")
def get_upload_columns(upload_id: int):
    db = SessionLocal()
    try:
        rec = db.query(UploadedFile).filter(UploadedFile.id == upload_id).first()
        if not rec:
            return JSONResponse(status_code=404, content={"error": "Upload not found"})
        return {"columns": rec.detected_columns, "filename": rec.filename}
    finally:
        db.close()



# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT: Single run detail
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/runs/{run_id}")
def get_run(run_id: int):
    db = SessionLocal()
    try:
        run = db.query(HistoryTable).filter(HistoryTable.id == run_id).first()
        if not run:
            return JSONResponse(status_code=404, content={"error": "Run not found"})

        reconciled = db.query(ReconciledRecord).filter(ReconciledRecord.run_id == run_id).all()
        reconciled_rows = []
        for r in reconciled:
            reconciled_rows.append({
                "id": r.id,
                "layer_matched": r.layer_matched,
                "match_type": r.match_type,
                "source_datetime": r.source_datetime.isoformat() if r.source_datetime else None,
                "dest_datetime": r.dest_datetime.isoformat() if r.dest_datetime else None,
                "source_amount": float(r.source_amount) if r.source_amount else None,
                "dest_amount": float(r.dest_amount) if r.dest_amount else None,
                "source_refs": r.source_refs,
                "dest_refs": r.dest_refs,
                "confidence_score": float(r.confidence_score) if r.confidence_score else None,
                "reason": r.reason,
            })

        return {
            "run": {
                "id": run.id,
                "source_filename": run.source_filename,
                "dest_filename": run.dest_filename,
                "status": run.status,
                "tol_amount": float(run.tol_amount) if run.tol_amount else 0,
                "tol_time_minutes": run.tol_time_minutes,
                "date_mode": run.date_mode,
                "total_source": run.total_source or 0,
                "total_dest": run.total_dest or 0,
                "total_matched": run.total_matched or 0,
                "total_unmatched": run.total_unmatched or 0,
                "layer0_count": run.layer0_count or 0,
                "layer1_count": run.layer1_count or 0,
                "layer2_count": run.layer2_count or 0,
                "layer3_count": run.layer3_count or 0,
                "layer4_count": run.layer4_count or 0,
                "layer5_count": run.layer5_count or 0,
                "layer0_time_sec": run.layer0_time_sec or 0,
                "layer1_time_sec": run.layer1_time_sec or 0,
                "layer2_time_sec": run.layer2_time_sec or 0,
                "layer3_time_sec": run.layer3_time_sec or 0,
                "layer4_time_sec": run.layer4_time_sec or 0,
                "layer5_time_sec": run.layer5_time_sec or 0,
                "total_duration_sec": run.total_duration_sec or 0,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "mapping_json": run.mapping_json,
            },
            "reconciled": reconciled_rows,
        }
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT: Download reconciled Excel
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/runs/{run_id}/download")
def download_run(run_id: int):
    db = SessionLocal()
    try:
        run = db.query(HistoryTable).filter(HistoryTable.id == run_id).first()
        if not run:
            return JSONResponse(status_code=404, content={"error": "Run not found"})

        path = run.excel_path
        if not path or not os.path.exists(path):
            # Try to generate on demand
            reconciled = db.query(ReconciledRecord).filter(ReconciledRecord.run_id == run_id).all()
            if not reconciled:
                return JSONResponse(status_code=404, content={"error": "No reconciled data to download"})
            path = export_to_excel(run_id, reconciled, db)
            run.excel_path = path
            db.commit()

        return FileResponse(
            path=path,
            filename=os.path.basename(path),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT: Get unreconciled records for a run
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/unreconciled/{run_id}")
def get_unreconciled(run_id: int):
    db = SessionLocal()
    try:
        run = db.query(HistoryTable).filter(HistoryTable.id == run_id).first()
        if not run:
            return JSONResponse(status_code=404, content={"error": "Run not found"})

        # Get reconciled IDs to exclude them
        reconciled = db.query(ReconciledRecord).filter(ReconciledRecord.run_id == run_id).all()
        reconciled_src_ids = {r.source_record_id for r in reconciled if r.source_record_id}
        reconciled_dest_ids = {r.dest_record_id for r in reconciled if r.dest_record_id}

        src_records = db.query(UnreconciledRecord).filter(
            UnreconciledRecord.upload_id == run.source_upload_id,
            UnreconciledRecord.side == "source",
        ).all()

        dest_records = db.query(UnreconciledRecord).filter(
            UnreconciledRecord.upload_id == run.dest_upload_id,
            UnreconciledRecord.side == "dest",
        ).all()

        def serialize(r):
            return {
                "id": r.id,
                "side": r.side,
                "txn_datetime": r.txn_datetime.isoformat() if r.txn_datetime else None,
                "amount": float(r.amount) if r.amount else None,
                "references": r.references,
                "remaining_columns": r.remaining_columns,
            }

        unmatched_src = [serialize(r) for r in src_records if r.id not in reconciled_src_ids]
        unmatched_dest = [serialize(r) for r in dest_records if r.id not in reconciled_dest_ids]

        return {
            "unmatched_source": unmatched_src,
            "unmatched_dest": unmatched_dest,
            "count_source": len(unmatched_src),
            "count_dest": len(unmatched_dest),
        }
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT: Manual reconcile
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/manual-reconcile")
def manual_reconcile(
    run_id: int = Form(...),
    source_record_id: int = Form(...),
    dest_record_id: int = Form(...),
):
    db = SessionLocal()
    try:
        src = db.query(UnreconciledRecord).filter(UnreconciledRecord.id == source_record_id).first()
        dest = db.query(UnreconciledRecord).filter(UnreconciledRecord.id == dest_record_id).first()

        if not src or not dest:
            return JSONResponse(status_code=404, content={"error": "Record(s) not found"})

        rec = ReconciledRecord(
            run_id=run_id,
            layer_matched="Manual",
            match_type="manual",
            source_record_id=source_record_id,
            source_datetime=src.txn_datetime,
            source_amount=src.amount,
            source_refs=src.references,
            dest_record_id=dest_record_id,
            dest_datetime=dest.txn_datetime,
            dest_amount=dest.amount,
            dest_refs=dest.references,
            confidence_score=1.0,
            reason="Manually reconciled by user",
        )
        db.add(rec)
        db.commit()

        return {"status": "reconciled", "id": rec.id}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT: Exclude record
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/exclude")
def exclude_record(
    record_id: int = Form(...),
    run_id: int = Form(None),
    reason: str = Form(""),
    side: str = Form(""),
):
    db = SessionLocal()
    try:
        record = db.query(UnreconciledRecord).filter(UnreconciledRecord.id == record_id).first()
        if not record:
            return JSONResponse(status_code=404, content={"error": "Record not found"})

        exc = ExcludeRecord(
            record_id=record_id,
            run_id=run_id,
            side=side or record.side,
            reason=reason,
        )
        db.add(exc)
        db.commit()

        return {"status": "excluded", "id": exc.id}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT: WebSocket progress
# ─────────────────────────────────────────────────────────────────────────────
@app.websocket("/ws/progress/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await manager.connect(websocket, job_id)
    try:
        # If job already finished, immediately send final status
        db = SessionLocal()
        try:
            run = db.query(HistoryTable).filter(HistoryTable.id == int(job_id)).first()
            if run and run.status == "completed":
                await websocket.send_json({
                    "status": "Reconciliation completed successfully!",
                    "progress": 100,
                    "total_matched": run.total_matched or 0,
                    "layer_counts": {
                        "Self Knock": run.layer0_count or 0,
                        "Exact Match": run.layer1_count or 0,
                        "Tolerance Match": run.layer2_count or 0,
                        "Subset Match": run.layer3_count or 0,
                        "Fuzzy Match": run.layer4_count or 0,
                        "LLM Match": run.layer5_count or 0,
                    },
                })
            elif run and run.status == "failed":
                await websocket.send_json({"status": "Error: Job failed", "progress": -1})
        finally:
            db.close()

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        manager.disconnect(websocket, job_id)
    except Exception:
        manager.disconnect(websocket, job_id)