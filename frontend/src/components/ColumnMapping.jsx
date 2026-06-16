import { useState, useEffect } from "react";
import axios from "axios";
import ProgressBar from "./ProgressBar";

const BASE = "http://localhost:8001";

export default function ColumnMapping({
  sourceCols,
  destCols,
  sourceUploadId,
  destUploadId
}) {
  const [mapping, setMapping] = useState({
    source: { datetime: "", amount: "", references: [] },
    dest: { datetime: "", amount: "", references: [] }
  });

  const [tolAmount, setTolAmount] = useState(10);
  const [tolTime, setTolTime] = useState(10);
  const [loading, setLoading] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState("");

  useEffect(() => {
    if (jobId) {
      const ws = new WebSocket(`ws://localhost:8001/ws/progress/${jobId}`);
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        setProgress(data.progress);
        setStatusMsg(data.status);
      };
      return () => ws.close();
    }
  }, [jobId]);

  const handleChange = (side, field, value) => {
    setMapping(prev => ({
      ...prev,
      [side]: { ...prev[side], [field]: value }
    }));
  };

  const handleRefs = (side, e) => {
    const values = Array.from(e.target.selectedOptions).map(o => o.value);
    setMapping(prev => ({
      ...prev,
      [side]: { ...prev[side], references: values }
    }));
  };

  const run = async () => {
    try {
      setLoading(true);
      setStatusMsg("Saving mappings...");
      setProgress(0);

      // 1) store mapped cols into postgres
      const ingestFd = new FormData();
      ingestFd.append("source_upload_id", sourceUploadId);
      ingestFd.append("dest_upload_id", destUploadId);
      ingestFd.append("mapping", JSON.stringify(mapping));

      await axios.post(`${BASE}/ingest-mapped`, ingestFd);

      // 2) start reconciliation using DB data
      setStatusMsg("Starting reconciliation engine...");
      const reconFd = new FormData();
      reconFd.append("source_upload_id", sourceUploadId);
      reconFd.append("dest_upload_id", destUploadId);
      reconFd.append("mapping", JSON.stringify(mapping));
      reconFd.append("tol_amount", tolAmount);
      reconFd.append("tol_time", tolTime);

      const res = await axios.post(`${BASE}/reconcile_async`, reconFd);
      setJobId(res.data.job_id);
    } catch (err) {
      console.error(err);
      setStatusMsg("Failed to run reconciliation: " + err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white p-6 rounded-xl shadow">
      <h2 className="text-lg font-bold mb-4">Column Mapping</h2>

      <div className="grid grid-cols-2 gap-6">
        <div>
          <h3 className="font-semibold mb-2">Source</h3>
          <select onChange={(e) => handleChange("source", "datetime", e.target.value)}>
            <option>Select Datetime</option>
            {sourceCols.map(c => <option key={c} value={c}>{c}</option>)}
          </select>

          <select onChange={(e) => handleChange("source", "amount", e.target.value)}>
            <option>Select Amount</option>
            {sourceCols.map(c => <option key={c} value={c}>{c}</option>)}
          </select>

          <select multiple onChange={(e) => handleRefs("source", e)}>
            {sourceCols.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>

        <div>
          <h3 className="font-semibold mb-2">Destination</h3>
          <select onChange={(e) => handleChange("dest", "datetime", e.target.value)}>
            <option>Select Datetime</option>
            {destCols.map(c => <option key={c} value={c}>{c}</option>)}
          </select>

          <select onChange={(e) => handleChange("dest", "amount", e.target.value)}>
            <option>Select Amount</option>
            {destCols.map(c => <option key={c} value={c}>{c}</option>)}
          </select>

          <select multiple onChange={(e) => handleRefs("dest", e)}>
            {destCols.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4">
        <input type="number" value={tolAmount} onChange={(e) => setTolAmount(e.target.value)} placeholder="Amount tolerance" />
        <input type="number" value={tolTime} onChange={(e) => setTolTime(e.target.value)} placeholder="Time tolerance (min)" />
      </div>

      <button
        onClick={run}
        disabled={loading}
        className="mt-4 bg-green-600 text-white px-4 py-2 rounded"
      >
        {loading ? "Processing..." : "Run Reconciliation"}
      </button>

      {statusMsg && (
        <div className="mt-6">
          <p className="text-sm font-medium mb-2">{statusMsg}</p>
          <ProgressBar progress={progress} />
        </div>
      )}
    </div>
  );
}