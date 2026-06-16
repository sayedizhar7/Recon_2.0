import { useState } from "react";
import axios from "axios";

const BASE = "http://localhost:8000";

const DATE_FORMATS = [
  { label: "DD/MM/YYYY", value: "%d/%m/%Y" },
  { label: "MM/DD/YYYY", value: "%m/%d/%Y" },
  { label: "YYYY-MM-DD", value: "%Y-%m-%d" },
  { label: "Auto Detect", value: "" },
];

const LAYER_INFO = [
  { name: "Self Knock", color: "var(--cyan)" },
  { name: "Exact Match", color: "var(--green)" },
  { name: "Tolerance Match", color: "var(--primary)" },
  { name: "Subset Match", color: "var(--amber)" },
  { name: "Fuzzy Match", color: "var(--purple)" },
  { name: "LLM Match", color: "var(--pink)" },
];

// ─────────────────────────────────────────────────────────────────────
// Template Picker Modal
// Replaces the old browser prompt() with a proper styled UI.
// Shows all saved templates as clickable cards with load/delete/rename.

function TemplatePickerModal({ onLoad, onClose }) {
  const [templates, setTemplates] = useState(() => {
    try { return JSON.parse(localStorage.getItem("reconTemplates") || "{}"); }
    catch { return {}; }
  });
  const [selected, setSelected] = useState(null);
  const [renaming, setRenaming] = useState(null); // name being renamed
  const [newName, setNewName] = useState("");

  const names = Object.keys(templates);

  const handleDelete = (name) => {
    const updated = { ...templates };
    delete updated[name];
    localStorage.setItem("reconTemplates", JSON.stringify(updated));
    setTemplates(updated);
    if (selected === name) setSelected(null);
  };

  const handleRename = (oldName) => {
    if (!newName.trim() || newName === oldName) { setRenaming(null); return; }
    const updated = { ...templates };
    updated[newName.trim()] = updated[oldName];
    delete updated[oldName];
    localStorage.setItem("reconTemplates", JSON.stringify(updated));
    setTemplates(updated);
    if (selected === oldName) setSelected(newName.trim());
    setRenaming(null);
    setNewName("");
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 500 }}>
        <div className="modal-title">
          <span>📂 Load Mapping Template</span>
          <button className="btn btn-outline btn-sm" onClick={onClose}>✕</button>
        </div>

        {names.length === 0 ? (
          <div style={{ textAlign: "center", color: "var(--text3)", padding: "32px 0" }}>
            <div style={{ fontSize: 32, marginBottom: 10 }}>📭</div>
            <div>No templates saved yet.</div>
            <div style={{ fontSize: 12, marginTop: 6 }}>Save a mapping in Step 2 to create one.</div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 20 }}>
            {names.map((name) => (
              <div
                key={name}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "10px 14px",
                  background: selected === name ? "rgba(79,142,247,.12)" : "var(--surface2)",
                  border: `1px solid ${selected === name ? "var(--primary)" : "var(--border)"}`,
                  borderRadius: 8, cursor: "pointer",
                  transition: "all .15s",
                }}
                onClick={() => setSelected(name)}
              >
                {renaming === name ? (
                  <input
                    className="form-input"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleRename(name)}
                    autoFocus
                    style={{ flex: 1, padding: "4px 8px", fontSize: 13 }}
                    onClick={(e) => e.stopPropagation()}
                  />
                ) : (
                  <span style={{ flex: 1, fontSize: 13, color: "var(--text)", fontWeight: selected === name ? 600 : 400 }}>
                    {selected === name ? "✓ " : ""}{name}
                  </span>
                )}
                <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                  {renaming === name ? (
                    <>
                      <button className="btn btn-sm btn-green" onClick={() => handleRename(name)}>Save</button>
                      <button className="btn btn-sm btn-outline" onClick={() => setRenaming(null)}>✕</button>
                    </>
                  ) : (
                    <>
                      <button
                        className="btn btn-sm btn-outline"
                        onClick={() => { setRenaming(name); setNewName(name); }}
                        title="Rename"
                      >✏️</button>
                      <button
                        className="btn btn-sm btn-red"
                        onClick={() => handleDelete(name)}
                        title="Delete"
                      >🗑</button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button className="btn btn-outline" onClick={onClose}>Cancel</button>
          <button
            className="btn btn-blue"
            disabled={!selected || !templates[selected]}
            onClick={() => { onLoad(templates[selected]); onClose(); }}
          >
            Load Selected →
          </button>
        </div>
      </div>
    </div>
  );
}

export default function TestRun() {
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const [srcFile, setSrcFile] = useState(null);
  const [destFile, setDestFile] = useState(null);
  const [uploadData, setUploadData] = useState(null);
  const [mapping, setMapping] = useState({
    source: { datetime: "", amount: "", references: [], date_format: "" },
    dest: { datetime: "", amount: "", references: [], date_format: "" },
    date_mode: "datetime",
  });
  const [tolAmount, setTolAmount] = useState(10);
  const [tolTime, setTolTime] = useState(10);
  const [tolUnit, setTolUnit] = useState("minutes");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState("");
  const [cleaningProgress, setCleaningProgress] = useState(-1);
  const [statusMsg, setStatusMsg] = useState("");

  const [uploadProgress, setUploadProgress] = useState(0);

  const ACCEPT = ".xlsx,.xls,.csv,.txt,.pdf,.xml,.lin";

  const handleUpload = async () => {
    if (!srcFile || !destFile) {
      setError("Select both files first.");
      return;
    }
    setError("");
    setLoading(true);
    setUploadProgress(0);
    try {
      const fd = new FormData();
      fd.append("source", srcFile);
      fd.append("dest", destFile);
      const res = await axios.post(`${BASE}/upload`, fd, {
        onUploadProgress: (e) => {
          if (e.total) {
            setUploadProgress(Math.round((100 * e.loaded) / e.total));
          }
        }
      });
      if (res.data.error) throw new Error(res.data.error);
      setUploadData(res.data);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Upload failed");
    } finally {
      setLoading(false);
    }
  };

  const handleLoadTemplate = () => {
    setShowTemplatePicker(true);
  };

  const handleSaveTemplate = () => {
    const name = prompt("Enter a name for this mapping template:");
    if (!name) return;
    const templates = JSON.parse(localStorage.getItem("reconTemplates") || "{}");
    templates[name] = mapping;
    localStorage.setItem("reconTemplates", JSON.stringify(templates));
    alert("Template saved!");
  };

  const toggleRef = (side, col) => {
    setMapping((prev) => {
      const refs = (prev[side].references || []).includes(col)
        ? prev[side].references.filter((r) => r !== col)
        : [...prev[side].references, col];
      return { ...prev, [side]: { ...prev[side], references: refs } };
    });
  };

  const handleChange = (side, field, val) => {
    setMapping((prev) => ({ ...prev, [side]: { ...prev[side], [field]: val } }));
  };

  const handleRun = async () => {
    setError("");
    setResults(null);

    if (!srcFile || !destFile) { setError("Select files first."); return; }
    if (!mapping.source.datetime || !mapping.dest.datetime) { setError("Select DateTime columns."); return; }
    if (!mapping.source.amount || !mapping.dest.amount) { setError("Select Amount columns."); return; }
    if (!(mapping.source.references || []).length || !(mapping.dest.references || []).length) { setError("Select at least one Reference."); return; }

    setLoading(true);
    setUploadProgress(0);
    setCleaningProgress(0);
    setStatusMsg("Starting run...");
    
    const clientId = Math.random().toString(36).substring(7);
    const ws = new WebSocket(`ws://localhost:8000/ws/progress/${clientId}`);
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.progress !== undefined) setCleaningProgress(data.progress);
        if (data.status) setStatusMsg(data.status);
      } catch (err) {}
    };

    try {
      const timeInMinutes = tolUnit === "days" ? tolTime * 24 * 60 : Number(tolTime);
      const fd = new FormData();
      fd.append("source", srcFile);
      fd.append("dest", destFile);
      fd.append("mapping", JSON.stringify(mapping));
      fd.append("tol_amount", tolAmount);
      fd.append("tol_time", timeInMinutes);
      fd.append("client_id", clientId);

      const res = await axios.post(`${BASE}/test-reconcile`, fd, {
        onUploadProgress: (e) => {
          if (e.total) {
            setUploadProgress(Math.round((100 * e.loaded) / e.total));
          }
        }
      });
      ws.close();
      setCleaningProgress(100);
      setStatusMsg("Done!");
      setResults(res.data);
      setTimeout(() => setCleaningProgress(-1), 2000);
    } catch (e) {
      ws.close();
      setCleaningProgress(-1);
      setError(e.response?.data?.error || e.message || "Test failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {showTemplatePicker && <TemplatePickerModal onLoad={(m) => setMapping(m)} onClose={() => setShowTemplatePicker(false)} />}
    <div>
      <div className="section-title">⚡ Test Reconciliation — No Database Write</div>
      <div className="alert alert-amber" style={{ marginBottom: 20 }}>
        ⚠️ Test mode: Files are processed in memory only. No data is saved to the database.
      </div>

      {/* File Upload */}
      <div className="card">
        <div className="card-header"><span className="card-title">📂 Select Files</span></div>
        <div className="card-body">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            <div>
              <div className="form-label">Source File</div>
              <div className={`upload-zone${srcFile ? " has-file" : ""}`} onClick={() => document.getElementById("t-src").click()}>
                <input id="t-src" type="file" accept={ACCEPT} style={{ display: "none" }} onChange={(e) => { setSrcFile(e.target.files[0]); setUploadData(null); }} />
                <div className="upload-zone-icon">{srcFile ? "✓" : "📄"}</div>
                <div className="upload-zone-text">{srcFile ? srcFile.name : "Click to select source file"}</div>
              </div>
            </div>
            <div>
              <div className="form-label">Destination File</div>
              <div className={`upload-zone${destFile ? " has-file" : ""}`} onClick={() => document.getElementById("t-dest").click()}>
                <input id="t-dest" type="file" accept={ACCEPT} style={{ display: "none" }} onChange={(e) => { setDestFile(e.target.files[0]); setUploadData(null); }} />
                <div className="upload-zone-icon">{destFile ? "✓" : "📄"}</div>
                <div className="upload-zone-text">{destFile ? destFile.name : "Click to select destination file"}</div>
              </div>
            </div>
          </div>
          
          {loading && uploadProgress > 0 && uploadProgress < 100 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6, fontSize: 13, color: "var(--text2)" }}>
                <span>Uploading files...</span>
                <span>{uploadProgress}%</span>
              </div>
              <div className="progress-bar">
                <div className="progress-fill" style={{ width: `${uploadProgress}%` }} />
              </div>
            </div>
          )}

          {loading && uploadProgress === 100 && !uploadData && (
            <div style={{ marginBottom: 16, fontSize: 13, color: "var(--text2)" }}>
              ⟳ Reading columns...
            </div>
          )}

          {srcFile && destFile && !uploadData && (
            <button className="btn btn-outline" onClick={handleUpload} disabled={loading}>
              {loading ? "⟳ Reading..." : "Read Columns"}
            </button>
          )}
        </div>
      </div>

      {/* Column Mapping */}
      {uploadData && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginBottom: 12 }}>
            <button className="btn btn-outline btn-sm" onClick={handleLoadTemplate}>
              📂 Load Template
            </button>
            <button className="btn btn-outline btn-sm" onClick={handleSaveTemplate}>
              💾 Save Template
            </button>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            {/* Source Mapping Card */}
            <div className="card">
              <div className="card-header">
                <span className="card-title">Source Mapping</span>
              </div>
              <div className="card-body">
                <div className="form-group">
                  <label className="form-label">DateTime</label>
                  <select className="form-select" value={mapping.source.datetime} onChange={(e) => handleChange("source", "datetime", e.target.value)}>
                    <option value="">— Select —</option>
                    {uploadData.source_columns.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Date Format (Source)</label>
                  <select className="form-select" value={mapping.source.date_format} onChange={(e) => handleChange("source", "date_format", e.target.value)}>
                    {DATE_FORMATS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Amount</label>
                  <select className="form-select" value={mapping.source.amount} onChange={(e) => handleChange("source", "amount", e.target.value)}>
                    <option value="">— Select —</option>
                    {uploadData.source_columns.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">References</label>
                  <div className="checkbox-group">
                    {uploadData.source_columns.map((c) => (
                      <label key={c} className="checkbox-item">
                        <input type="checkbox" checked={(mapping.source.references || []).includes(c)} onChange={() => toggleRef("source", c)} />
                        {c}
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Destination Mapping Card */}
            <div className="card">
              <div className="card-header">
                <span className="card-title">Destination Mapping</span>
              </div>
              <div className="card-body">
                <div className="form-group">
                  <label className="form-label">DateTime</label>
                  <select className="form-select" value={mapping.dest.datetime} onChange={(e) => handleChange("dest", "datetime", e.target.value)}>
                    <option value="">— Select —</option>
                    {uploadData.dest_columns.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Date Format (Dest)</label>
                  <select className="form-select" value={mapping.dest.date_format} onChange={(e) => handleChange("dest", "date_format", e.target.value)}>
                    {DATE_FORMATS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Amount</label>
                  <select className="form-select" value={mapping.dest.amount} onChange={(e) => handleChange("dest", "amount", e.target.value)}>
                    <option value="">— Select —</option>
                    {uploadData.dest_columns.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">References</label>
                  <div className="checkbox-group">
                    {uploadData.dest_columns.map((c) => (
                      <label key={c} className="checkbox-item">
                        <input type="checkbox" checked={(mapping.dest.references || []).includes(c)} onChange={() => toggleRef("dest", c)} />
                        {c}
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Settings */}
      {uploadData && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-header"><span className="card-title">⚙️ Settings</span></div>
          <div className="card-body" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
            <div className="form-group">
              <label className="form-label">Date Mode</label>
              <div style={{ display: "flex", gap: 6 }}>
                {["date", "datetime"].map((m) => (
                  <button key={m} className={`btn btn-sm ${mapping.date_mode === m ? "btn-blue" : "btn-outline"}`} onClick={() => setMapping(p => ({ ...p, date_mode: m }))}>
                    {m}
                  </button>
                ))}
              </div>
            </div>
            
            <div className="form-group">
              <label className="form-label">Amount Tolerance</label>
              <input className="form-input" type="number" min={0} value={tolAmount} onChange={(e) => setTolAmount(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Time Tolerance</label>
              <div style={{ display: "flex", gap: 6 }}>
                <input className="form-input" type="number" min={0} value={tolTime} onChange={(e) => setTolTime(e.target.value)} style={{ flex: 1 }} />
                <select className="form-select" style={{ width: 90 }} value={tolUnit} onChange={(e) => setTolUnit(e.target.value)}>
                  <option value="minutes">Min</option>
                  <option value="days">Days</option>
                </select>
              </div>
            </div>
          </div>
        </div>
      )}

      {error && <div className="alert alert-red" style={{ marginBottom: 12 }}>{error}</div>}

      {uploadData && (
        <button className="btn btn-blue" onClick={handleRun} disabled={loading} style={{ fontSize: 14 }}>
          {loading ? "⟳ Running test..." : "⚡ Run Test Reconciliation"}
        </button>
      )}

      {cleaningProgress >= 0 && (
        <div className="card" style={{ marginTop: 20 }}>
          <div className="card-body">
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6, fontSize: 13, color: "var(--text2)" }}>
              <span>{statusMsg || "Processing data..."}</span>
              <span>{cleaningProgress}%</span>
            </div>
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${cleaningProgress}%` }} />
            </div>
          </div>
        </div>
      )}

      {/* Results */}
      {results && (
        <div style={{ marginTop: 24 }}>
          <div className="section-title">Test Results</div>
          <div className="kpi-grid">
            <div className="kpi-card">
              <div className="kpi-label">Source Rows</div>
              <div className="kpi-value" style={{ color: "var(--cyan)", fontSize: 22 }}>{results.total_source}</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Dest Rows</div>
              <div className="kpi-value" style={{ color: "var(--purple)", fontSize: 22 }}>{results.total_dest}</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Total Matched</div>
              <div className="kpi-value" style={{ color: "var(--green)", fontSize: 22 }}>{results.total_matched}</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Src Unmatched</div>
              <div className="kpi-value" style={{ color: "var(--amber)", fontSize: 22 }}>{results.total_unmatched_src}</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Dest Unmatched</div>
              <div className="kpi-value" style={{ color: "var(--amber)", fontSize: 22 }}>{results.total_unmatched_dest}</div>
            </div>
          </div>

          <div className="layer-cards">
            {LAYER_INFO.map((l) => {
              const d = results.layers?.[l.name];
              return (
                <div key={l.name} className={`layer-card${d && d.count > 0 ? " done" : ""}`}>
                  <div className="layer-card-name">{l.name}</div>
                  <div className="layer-card-count" style={{ color: d?.count > 0 ? l.color : "var(--text3)" }}>
                    {d ? d.count : "—"}
                  </div>
                  {d?.time_sec != null && <div className="layer-card-time">⏱ {d.time_sec}s</div>}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
    </>
  );
}
