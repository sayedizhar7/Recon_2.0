import { useEffect, useState } from "react";
import axios from "axios";

const BASE = "http://localhost:8000";

const LAYERS = [
  { key: "layer0", name: "Self Knock", color: "var(--cyan)" },
  { key: "layer1", name: "Exact Match", color: "var(--green)" },
  { key: "layer2", name: "Tolerance", color: "var(--primary)" },
  { key: "layer3", name: "Subset", color: "var(--amber)" },
  { key: "layer4", name: "Fuzzy", color: "var(--purple)" },
  { key: "layer5", name: "LLM", color: "var(--pink)" },
];

function LayerKPICard({ name, count, timeSec, color }) {
  return (
    <div className="kpi-card" style={{ borderLeft: `3px solid ${color}` }}>
      <div className="kpi-label" style={{ color }}>{name}</div>
      <div className="kpi-value" style={{ fontSize: 24 }}>{(count || 0).toLocaleString()}</div>
      <div className="kpi-sub">⏱ {timeSec ? `${timeSec}s` : "—"}</div>
    </div>
  );
}

export default function RunDetail({ runId, navigate }) {
  const [data, setData] = useState(null);
  const [unmatched, setUnmatched] = useState(null);
  const [tab, setTab] = useState("matched");
  const [loading, setLoading] = useState(true);
  const [downloadLoading, setDownloadLoading] = useState(false);
  const [manualSrc, setManualSrc] = useState(null);
  const [manualDest, setManualDest] = useState(null);
  const [actionMsg, setActionMsg] = useState("");

  useEffect(() => {
    if (!runId) return;
    fetchData();
  }, [runId]);

  const fetchData = async () => {
    try {
      const [runRes, unmatchedRes] = await Promise.all([
        axios.get(`${BASE}/runs/${runId}`),
        axios.get(`${BASE}/unreconciled/${runId}`),
      ]);
      setData(runRes.data);
      setUnmatched(unmatchedRes.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async () => {
    setDownloadLoading(true);
    try {
      window.open(`${BASE}/runs/${runId}/download`, "_blank");
    } finally {
      setDownloadLoading(false);
    }
  };

  const handleManualRecon = async () => {
    if (!manualSrc || !manualDest) return;
    try {
      const fd = new FormData();
      fd.append("run_id", runId);
      fd.append("source_record_id", manualSrc);
      fd.append("dest_record_id", manualDest);
      await axios.post(`${BASE}/manual-reconcile`, fd);
      setActionMsg("✓ Manually reconciled!");
      setManualSrc(null);
      setManualDest(null);
      fetchData();
    } catch (e) {
      setActionMsg("❌ Failed: " + e.message);
    }
  };

  const handleExclude = async (recordId, side) => {
    try {
      const fd = new FormData();
      fd.append("record_id", recordId);
      fd.append("run_id", runId);
      fd.append("side", side);
      fd.append("reason", "Excluded by user");
      await axios.post(`${BASE}/exclude`, fd);
      setActionMsg("✓ Excluded!");
      fetchData();
    } catch (e) {
      setActionMsg("❌ Failed: " + e.message);
    }
  };

  if (loading) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">⟳</div>
        <div className="empty-state-text">Loading run details...</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">⚠️</div>
        <div className="empty-state-text">Run not found</div>
        <button className="btn btn-outline" style={{ marginTop: 16 }} onClick={() => navigate("history")}>
          ← Back to History
        </button>
      </div>
    );
  }

  const run = data.run;
  const reconciled = data.reconciled || [];

  return (
    <div>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
        <button className="btn btn-outline btn-sm" onClick={() => navigate("history")}>← Back</button>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "var(--text)" }}>
            Run #{run.id}
            <span className={`badge badge-${run.status === "completed" ? "green" : "blue"}`} style={{ marginLeft: 10 }}>
              {run.status}
            </span>
          </div>
          <div style={{ fontSize: 12, color: "var(--text3)", marginTop: 2 }}>
            {run.source_filename} → {run.dest_filename}
          </div>
        </div>
        <div style={{ marginLeft: "auto" }}>
          <button className="btn btn-green btn-sm" onClick={handleDownload} disabled={downloadLoading}>
            {downloadLoading ? "⟳" : "⬇"} Download Excel
          </button>
        </div>
      </div>

      {/* Summary KPI */}
      <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", marginBottom: 20 }}>
        <div className="kpi-card">
          <div className="kpi-label">Source Rows</div>
          <div className="kpi-value" style={{ color: "var(--cyan)", fontSize: 22 }}>
            {(run.total_source || 0).toLocaleString()}
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Dest Rows</div>
          <div className="kpi-value" style={{ color: "var(--purple)", fontSize: 22 }}>
            {(run.total_dest || 0).toLocaleString()}
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Total Matched</div>
          <div className="kpi-value" style={{ color: "var(--green)", fontSize: 22 }}>
            {(run.total_matched || 0).toLocaleString()}
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Total Unmatched</div>
          <div className="kpi-value" style={{ color: "var(--amber)", fontSize: 22 }}>
            {(run.total_unmatched || 0).toLocaleString()}
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Duration</div>
          <div className="kpi-value" style={{ color: "var(--text)", fontSize: 22 }}>
            {run.total_duration_sec ? `${run.total_duration_sec}s` : "—"}
          </div>
        </div>
      </div>

      {/* Per-layer KPI cards */}
      <div className="section-title">Layer Breakdown</div>
      <div className="kpi-grid" style={{ marginBottom: 24 }}>
        {LAYERS.map((l) => (
          <LayerKPICard
            key={l.key}
            name={l.name}
            count={run[`${l.key}_count`]}
            timeSec={run[`${l.key}_time_sec`]}
            color={l.color}
          />
        ))}
      </div>

      {/* Tabs */}
      <div className="tabs">
        <div className={`tab${tab === "matched" ? " active" : ""}`} onClick={() => setTab("matched")}>
          Matched Records ({reconciled.length})
        </div>
        <div className={`tab${tab === "unmatched" ? " active" : ""}`} onClick={() => setTab("unmatched")}>
          Unmatched ({(unmatched?.count_source || 0) + (unmatched?.count_dest || 0)})
        </div>
      </div>

      {actionMsg && (
        <div className={`alert ${actionMsg.startsWith("✓") ? "alert-green" : "alert-red"}`} style={{ marginBottom: 12 }}>
          {actionMsg}
        </div>
      )}

      {/* Matched Records */}
      {tab === "matched" && (
        <div className="card">
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>Layer</th>
                  <th>Match Type</th>
                  <th>Src Datetime</th>
                  <th>Dest Datetime</th>
                  <th>Src Amount</th>
                  <th>Dest Amount</th>
                  <th>Confidence</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {reconciled.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <span className="badge badge-blue">{r.layer_matched}</span>
                    </td>
                    <td style={{ color: "var(--text3)" }}>{r.match_type || "—"}</td>
                    <td>{r.source_datetime ? new Date(r.source_datetime).toLocaleString() : "—"}</td>
                    <td>{r.dest_datetime ? new Date(r.dest_datetime).toLocaleString() : "—"}</td>
                    <td style={{ color: "var(--green)" }}>
                      {r.source_amount != null ? r.source_amount.toLocaleString() : "—"}
                    </td>
                    <td style={{ color: "var(--cyan)" }}>
                      {r.dest_amount != null ? r.dest_amount.toLocaleString() : "—"}
                    </td>
                    <td>
                      <span className="badge badge-amber">
                        {r.confidence_score != null ? (r.confidence_score * 100).toFixed(0) + "%" : "—"}
                      </span>
                    </td>
                    <td style={{ color: "var(--text3)", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {r.reason || "—"}
                    </td>
                  </tr>
                ))}
                {reconciled.length === 0 && (
                  <tr>
                    <td colSpan={8} style={{ textAlign: "center", color: "var(--text3)", padding: "30px" }}>
                      No matched records found
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Unmatched Records */}
      {tab === "unmatched" && unmatched && (
        <div>
          {manualSrc && manualDest && (
            <div className="alert alert-blue" style={{ marginBottom: 12, justifyContent: "space-between" }}>
              <span>Ready to reconcile Src #{manualSrc} ↔ Dest #{manualDest}</span>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn btn-green btn-sm" onClick={handleManualRecon}>Confirm</button>
                <button className="btn btn-outline btn-sm" onClick={() => { setManualSrc(null); setManualDest(null); }}>Cancel</button>
              </div>
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            {/* Source unmatched */}
            <div className="card">
              <div className="card-header">
                <span className="card-title">Unmatched Source ({unmatched.count_source})</span>
              </div>
              <div className="tbl-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Datetime</th>
                      <th>Amount</th>
                      <th>Refs</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {(unmatched.unmatched_source || []).slice(0, 50).map((r) => (
                      <tr key={r.id}>
                        <td style={{ color: "var(--text3)" }}>#{r.id}</td>
                        <td>{r.txn_datetime ? new Date(r.txn_datetime).toLocaleDateString() : "—"}</td>
                        <td style={{ color: "var(--green)" }}>{r.amount?.toLocaleString() || "—"}</td>
                        <td style={{ color: "var(--text3)", fontSize: 11 }}>
                          {Object.values(r.references || {}).join(", ").slice(0, 30)}
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: 4 }}>
                            <button
                              className={`btn btn-sm ${manualSrc === r.id ? "btn-blue" : "btn-outline"}`}
                              onClick={() => setManualSrc(r.id)}
                            >
                              {manualSrc === r.id ? "✓" : "Select"}
                            </button>
                            <button className="btn btn-sm btn-red" onClick={() => handleExclude(r.id, "source")}>
                              Excl
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Dest unmatched */}
            <div className="card">
              <div className="card-header">
                <span className="card-title">Unmatched Dest ({unmatched.count_dest})</span>
              </div>
              <div className="tbl-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Datetime</th>
                      <th>Amount</th>
                      <th>Refs</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {(unmatched.unmatched_dest || []).slice(0, 50).map((r) => (
                      <tr key={r.id}>
                        <td style={{ color: "var(--text3)" }}>#{r.id}</td>
                        <td>{r.txn_datetime ? new Date(r.txn_datetime).toLocaleDateString() : "—"}</td>
                        <td style={{ color: "var(--cyan)" }}>{r.amount?.toLocaleString() || "—"}</td>
                        <td style={{ color: "var(--text3)", fontSize: 11 }}>
                          {Object.values(r.references || {}).join(", ").slice(0, 30)}
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: 4 }}>
                            <button
                              className={`btn btn-sm ${manualDest === r.id ? "btn-purple" : "btn-outline"}`}
                              onClick={() => setManualDest(r.id)}
                            >
                              {manualDest === r.id ? "✓" : "Select"}
                            </button>
                            <button className="btn btn-sm btn-red" onClick={() => handleExclude(r.id, "dest")}>
                              Excl
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
