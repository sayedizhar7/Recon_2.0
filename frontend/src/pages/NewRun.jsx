import { useState, useEffect, useRef } from "react";
import axios from "axios";

const BASE = "http://localhost:8000";

const LAYER_INFO = [
  { name: "Self Knock", color: "var(--cyan)" },
  { name: "Exact Match", color: "var(--green)" },
  { name: "Tolerance Match", color: "var(--primary)" },
  { name: "Subset Match", color: "var(--amber)" },
  { name: "Fuzzy Match", color: "var(--purple)" },
  { name: "LLM Match", color: "var(--pink)" },
];

const DATE_FORMATS = [
  { label: "Auto Detect", value: "" },
  { label: "DD/MM/YYYY", value: "%d/%m/%Y" },
  { label: "MM/DD/YYYY", value: "%m/%d/%Y" },
  { label: "YYYY-MM-DD", value: "%Y-%m-%d" },
  { label: "DD-MM-YYYY", value: "%d-%m-%Y" },
  { label: "DD/MM/YY", value: "%d/%m/%y" },
];

// ─────────────────────────────────────────────────────────────────────
// Template Picker Modal
// Replaces the old browser prompt() with a proper styled UI.
// Shows all saved templates as clickable cards with load/delete/rename.
// ─────────────────────────────────────────────────────────────────────
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

// Step 1: File Upload with per-file progress
function StepUpload({ onDone }) {
  const [srcFile, setSrcFile] = useState(null);
  const [destFile, setDestFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [srcProgress, setSrcProgress] = useState(0); // per-file visual split
  const [destProgress, setDestProgress] = useState(0);
  const [phase, setPhase] = useState(""); // "uploading" | "reading" | ""

  const ACCEPT = ".xlsx,.xls,.csv,.txt,.pdf,.xml,.lin";

  const handleUpload = async () => {
    if (!srcFile || !destFile) {
      setError("Please select both source and destination files.");
      return;
    }
    setError("");
    setLoading(true);
    setUploadProgress(0);
    setSrcProgress(0);
    setDestProgress(0);
    setPhase("uploading");

    // Estimate per-file share based on file size
    const totalSize = srcFile.size + destFile.size;
    const srcShare = totalSize > 0 ? srcFile.size / totalSize : 0.5;
    const destShare = 1 - srcShare;

    try {
      const fd = new FormData();
      fd.append("source", srcFile);
      fd.append("dest", destFile);
      const res = await axios.post(`${BASE}/upload`, fd, {
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total) {
            const pct = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            setUploadProgress(pct);
            // Distribute progress proportionally to each file's size
            setSrcProgress(Math.min(100, Math.round(pct / srcShare)));
            setDestProgress(Math.min(100, Math.round(pct / destShare)));
          }
        }
      });
      setPhase("reading");
      if (res.data.error) throw new Error(res.data.error);
      setSrcProgress(100);
      setDestProgress(100);
      onDone(res.data);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Upload failed");
    } finally {
      setLoading(false);
      setPhase("");
    }
  };

  const DropZone = ({ label, file, setFile, id }) => (
    <div
      className={`upload-zone${file ? " has-file" : ""}`}
      onClick={() => document.getElementById(id).click()}
    >
      <input
        id={id}
        type="file"
        accept={ACCEPT}
        style={{ display: "none" }}
        onChange={(e) => setFile(e.target.files[0])}
      />
      <div className="upload-zone-icon">{file ? "✓" : "📄"}</div>
      <div className="upload-zone-text">
        {file ? file.name : `Click to select ${label} file`}
      </div>
      <div className="upload-zone-sub">
        {file
          ? `${(file.size / 1024).toFixed(1)} KB`
          : "XLSX, XLS, CSV, TXT, PDF, XML, LIN"}
      </div>
    </div>
  );

  const FileProgressBar = ({ label, file, progress, color }) => {
    if (!file || !loading) return null;
    return (
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--text2)", marginBottom: 4 }}>
          <span>{label}: <span style={{ color: "var(--text)" }}>{file.name}</span></span>
          <span style={{ color }}>{phase === "reading" ? "Reading columns..." : `${Math.min(progress, 100)}%`}</span>
        </div>
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${phase === "reading" ? 100 : Math.min(progress, 100)}%`, background: color }} />
        </div>
      </div>
    );
  };

  return (
    <div>
      <div className="section-title">Step 1 — Upload Files</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 20 }}>
        <div>
          <div className="form-label" style={{ marginBottom: 8 }}>Source File</div>
          <DropZone label="source" file={srcFile} setFile={setSrcFile} id="src-upload" />
        </div>
        <div>
          <div className="form-label" style={{ marginBottom: 8 }}>Destination File</div>
          <DropZone label="destination" file={destFile} setFile={setDestFile} id="dest-upload" />
        </div>
      </div>

      {error && <div className="alert alert-red" style={{ marginBottom: 12 }}>{error}</div>}

      {loading && (
        <div style={{ marginBottom: 16 }}>
          <FileProgressBar label="Source" file={srcFile} progress={srcProgress} color="var(--cyan)" />
          <FileProgressBar label="Destination" file={destFile} progress={destProgress} color="var(--purple)" />
          {phase === "reading" && (
            <div style={{ fontSize: 12, color: "var(--text3)", marginTop: 8, textAlign: "center" }}>⟳ Reading column headers...</div>
          )}
        </div>
      )}

      {srcFile && destFile && (
        <button className="btn btn-blue" onClick={handleUpload} disabled={loading}>
          {loading ? "⟳ Processing..." : "Done — Read Columns →"}
        </button>
      )}
    </div>
  );
}

// Step 2: Column Mapping with per-side date formats and template picker modal
function StepMapping({ uploadData, onDone, initialMapping }) {
  const { source_columns: srcCols, dest_columns: destCols } = uploadData;

  const defaultMapping = {
    source: { datetime: "", amount: "", references: [], date_format: "", date_mode: "datetime" },
    dest: { datetime: "", amount: "", references: [], date_format: "", date_mode: "datetime" },
    date_mode: "datetime",
    date_format: "",
  };

  const [mapping, setMapping] = useState(initialMapping || defaultMapping);
  const [error, setError] = useState("");
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const [saveNameInput, setSaveNameInput] = useState("");
  const [showSaveInput, setShowSaveInput] = useState(false);

  const handleSaveTemplate = () => {
    if (!saveNameInput.trim()) return;
    const templates = JSON.parse(localStorage.getItem("reconTemplates") || "{}");
    templates[saveNameInput.trim()] = mapping;
    localStorage.setItem("reconTemplates", JSON.stringify(templates));
    setSaveNameInput("");
    setShowSaveInput(false);
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

  const handleGlobal = (field, val) => {
    setMapping((prev) => ({ ...prev, [field]: val }));
  };

  const validate = () => {
    const { source, dest } = mapping;
    if (!source.datetime || !dest.datetime) return "Please select DateTime for both files.";
    if (!source.amount || !dest.amount) return "Please select Amount for both files.";
    if (!source.references.length || !dest.references.length) return "Please select at least one Reference for each file.";
    return "";
  };

  const handleNext = () => {
    const err = validate();
    if (err) { setError(err); return; }
    setError("");
    onDone(mapping);
  };

  const renderSideCard = (side, cols, label, icon) => (
    <div className="card">
      <div className="card-header">
        <span style={{ fontSize: 14 }}>{icon}</span>
        <span className="card-title">{label}</span>
      </div>
      <div className="card-body">
        <div className="form-group">
          <label className="form-label">📅 DateTime Column</label>
          <select
            className="form-select"
            value={mapping[side].datetime}
            onChange={(e) => handleChange(side, "datetime", e.target.value)}
          >
            <option value="">— Select —</option>
            {cols.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>

        <div className="form-group">
          <label className="form-label">💰 Amount Column</label>
          <select
            className="form-select"
            value={mapping[side].amount}
            onChange={(e) => handleChange(side, "amount", e.target.value)}
          >
            <option value="">— Select —</option>
            {cols.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>

        {/* Per-side date format — independent for source and destination */}
        <div className="form-group">
          <label className="form-label">📆 Date Format (this file)</label>
          <select
            className="form-select"
            value={mapping[side].date_format ?? ""}
            onChange={(e) => handleChange(side, "date_format", e.target.value)}
          >
            {DATE_FORMATS.map((f) => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>
          <div className="helper-text" style={{ marginTop: 4 }}>Can differ between source and destination</div>
        </div>

        <div className="form-group">
          <label className="form-label">🔗 Reference Columns (select all that apply)</label>
          <div className="checkbox-group">
            {cols.map((c) => (
              <label key={c} className="checkbox-item">
                <input
                  type="checkbox"
                  checked={(mapping[side].references || []).includes(c)}
                  onChange={() => toggleRef(side, c)}
                />
                {c}
              </label>
            ))}
          </div>
          {(mapping[side].references || []).length > 0 && (
            <div className="helper-text" style={{ marginTop: 6 }}>
              Selected: {(mapping[side].references || []).join(", ")}
            </div>
          )}
        </div>
      </div>
    </div>
  );

  return (
    <div>
      {showTemplatePicker && (
        <TemplatePickerModal
          onLoad={(t) => setMapping({ ...defaultMapping, ...t })}
          onClose={() => setShowTemplatePicker(false)}
        />
      )}

      <div className="section-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>Step 2 — Column Mapping</span>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {showSaveInput ? (
            <>
              <input
                className="form-input"
                value={saveNameInput}
                onChange={(e) => setSaveNameInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSaveTemplate()}
                placeholder="Template name..."
                autoFocus
                style={{ width: 180, padding: "5px 10px", fontSize: 12 }}
              />
              <button className="btn btn-green btn-sm" onClick={handleSaveTemplate} disabled={!saveNameInput.trim()}>💾 Save</button>
              <button className="btn btn-outline btn-sm" onClick={() => setShowSaveInput(false)}>✕</button>
            </>
          ) : (
            <>
              <button className="btn btn-outline btn-sm" onClick={() => setShowTemplatePicker(true)}>📂 Load Template</button>
              <button className="btn btn-outline btn-sm" onClick={() => setShowSaveInput(true)}>💾 Save Template</button>
            </>
          )}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
        {renderSideCard("source", srcCols, "Source File", "📥")}
        {renderSideCard("dest", destCols, "Destination File", "📤")}
      </div>

      {/* Global Date Mode — applies to both sides */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">⚙️ Date Type (applies to both files)</span>
        </div>
        <div className="card-body">
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">Interpret dates as:</label>
            <div style={{ display: "flex", gap: 8 }}>
              {["date", "datetime"].map((m) => (
                <button
                  key={m}
                  className={`btn btn-sm ${mapping.date_mode === m ? "btn-blue" : "btn-outline"}`}
                  onClick={() => handleGlobal("date_mode", m)}
                >
                  {m === "date" ? "📅 Date only" : "🕐 Date + Time"}
                </button>
              ))}
            </div>
            <div className="helper-text" style={{ marginTop: 6 }}>
              Date only: ignores time component. Date + Time: uses time up to the minute.
            </div>
          </div>
        </div>
      </div>

      {error && <div className="alert alert-red" style={{ marginBottom: 12 }}>{error}</div>}

      <button className="btn btn-blue" onClick={handleNext}>
        Next — Set Tolerances →
      </button>
    </div>
  );
}

// Step 3: Tolerances
function StepTolerances({ mapping, onDone }) {
  const [tolAmount, setTolAmount] = useState(10);
  const [tolTime, setTolTime] = useState(10);
  const [tolUnit, setTolUnit] = useState("minutes");

  const handleRun = () => {
    const timeInMinutes = tolUnit === "days" ? tolTime * 24 * 60 : Number(tolTime);
    onDone({ tolAmount: Number(tolAmount), tolTime: timeInMinutes, mapping });
  };

  return (
    <div>
      <div className="section-title">Step 3 — Tolerance Settings</div>
      <div className="card">
        <div className="card-body">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
            <div className="form-group">
              <label className="form-label">💰 Amount Tolerance</label>
              <input
                className="form-input"
                type="number"
                min={0}
                value={tolAmount}
                onChange={(e) => setTolAmount(e.target.value)}
                placeholder="e.g. 10"
              />
              <div className="helper-text">Max allowed difference in amount between records</div>
            </div>

            <div className="form-group">
              <label className="form-label">⏱ Time Tolerance</label>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  className="form-input"
                  type="number"
                  min={0}
                  value={tolTime}
                  onChange={(e) => setTolTime(e.target.value)}
                  placeholder="e.g. 10"
                  style={{ flex: 1 }}
                />
                <div style={{ display: "flex", gap: 4 }}>
                  {["minutes", "days"].map((u) => (
                    <button
                      key={u}
                      className={`btn btn-sm ${tolUnit === u ? "btn-blue" : "btn-outline"}`}
                      onClick={() => setTolUnit(u)}
                    >
                      {u}
                    </button>
                  ))}
                </div>
              </div>
              <div className="helper-text">Max allowed time difference between records</div>
            </div>
          </div>
        </div>
      </div>

      <div className="alert alert-blue" style={{ marginBottom: 16 }}>
        ℹ️ Date mode: <strong>{mapping.date_mode}</strong> |
        Date format: <strong>{mapping.date_format || "Auto Detect"}</strong>
      </div>

      <button className="btn btn-green" onClick={handleRun} style={{ fontSize: 14 }}>
        ▶ Upload & Run Reconciliation
      </button>
    </div>
  );
}

// Step 4: Live Tracking
function StepTracking({ runId, onViewResults }) {
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState("Connecting...");
  const [layerData, setLayerData] = useState({});
  const [done, setDone] = useState(false);
  const wsRef = useRef(null);

  useEffect(() => {
    if (!runId) return;

    const ws = new WebSocket(`ws://localhost:8000/ws/progress/${runId}`);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setProgress(data.progress || 0);
      setStatusMsg(data.status || "");

      if (data.layer && data.count !== undefined) {
        setLayerData((prev) => ({
          ...prev,
          [data.layer]: { count: data.count, time: data.time_sec },
        }));
      }

      if (data.layer_counts) {
        const newLayers = {};
        Object.entries(data.layer_counts).forEach(([name, count]) => {
          newLayers[name] = { count, time: data.layer_times?.[name] };
        });
        setLayerData(newLayers);
      }

      if (data.progress === 100 || data.progress === -1) {
        setDone(true);
        ws.close();
      }
    };

    ws.onerror = () => setStatusMsg("WebSocket error");
    ws.onclose = () => { if (!done) setStatusMsg("Connection closed"); };

    return () => ws.close();
  }, [runId]);

  const isError = progress === -1;

  return (
    <div>
      <div className="section-title">Step 4 — Live Tracking</div>

      <div className="card">
        <div className="card-body">
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
            <span style={{ fontSize: 13, color: "var(--text2)" }}>{statusMsg}</span>
            <span style={{ fontSize: 13, fontWeight: 700, color: isError ? "var(--red)" : "var(--primary)" }}>
              {isError ? "Error" : `${Math.max(0, progress)}%`}
            </span>
          </div>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{
                width: `${Math.max(0, progress)}%`,
                background: isError ? "var(--red)" : undefined,
              }}
            />
          </div>
        </div>
      </div>

      {/* Layer cards */}
      {Object.keys(layerData).length > 0 && (
        <div>
          <div className="section-title" style={{ marginTop: 20 }}>Layer Results</div>
          <div className="layer-cards">
            {LAYER_INFO.map((l) => {
              const d = layerData[l.name];
              return (
                <div key={l.name} className={`layer-card${d ? " done" : ""}`}>
                  <div className="layer-card-name">{l.name}</div>
                  <div className="layer-card-count" style={{ color: d ? l.color : "var(--text3)" }}>
                    {d ? d.count.toLocaleString() : "—"}
                  </div>
                  {d?.time != null && (
                    <div className="layer-card-time">⏱ {d.time}s</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {done && !isError && (
        <div style={{ marginTop: 20 }}>
          <div className="alert alert-green" style={{ marginBottom: 16 }}>
            ✓ Reconciliation completed successfully!
          </div>
          <button className="btn btn-blue" onClick={() => onViewResults(runId)}>
            View Results →
          </button>
        </div>
      )}

      {isError && (
        <div className="alert alert-red" style={{ marginTop: 16 }}>
          ❌ {statusMsg}
        </div>
      )}
    </div>
  );
}

export default function NewRun({ navigate, initialMapping, initialSourceUploadId, initialDestUploadId }) {
  const [step, setStep] = useState(1);
  const [uploadData, setUploadData] = useState(null);
  const [mapping, setMapping] = useState(null);
  const [jobId, setJobId] = useState(null);
  const [error, setError] = useState("");
  const [cleaningProgress, setCleaningProgress] = useState(-1);
  const [statusMsg, setStatusMsg] = useState("");

  // Update mapping if initialMapping changes
  useEffect(() => {
    if (initialMapping && step <= 2) {
      setMapping(initialMapping);
    }
  }, [initialMapping, step]);

  // Fetch columns if upload IDs are already provided
  useEffect(() => {
    if (initialSourceUploadId && initialDestUploadId) {
      const loadPreExistingCols = async () => {
        try {
          const res1 = await axios.get(`${BASE}/uploads/${initialSourceUploadId}/columns`);
          const res2 = await axios.get(`${BASE}/uploads/${initialDestUploadId}/columns`);
          setUploadData({
            source_upload_id: initialSourceUploadId,
            dest_upload_id: initialDestUploadId,
            source_columns: res1.data.columns,
            dest_columns: res2.data.columns,
          });
          setStep(2);
        } catch (e) {
          setError(e.response?.data?.error || e.message || "Failed to load columns for the previous run.");
        }
      };
      loadPreExistingCols();
    }
  }, [initialSourceUploadId, initialDestUploadId]);

  const handleUploadDone = (data) => {
    setUploadData(data);
    setStep(2);
  };

  const handleMappingDone = (mappingData) => {
    setMapping(mappingData);
    setStep(3);
  };

  const handleRunStart = async ({ tolAmount, tolTime, mapping: mappingData }) => {
    setError("");
    setCleaningProgress(0);
    setStatusMsg("Starting ingestion...");

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
      // 1. Ingest
      const ingestFd = new FormData();
      ingestFd.append("source_upload_id", uploadData.source_upload_id);
      ingestFd.append("dest_upload_id", uploadData.dest_upload_id);
      ingestFd.append("mapping", JSON.stringify(mappingData));
      ingestFd.append("client_id", clientId);
      await axios.post(`${BASE}/ingest-mapped`, ingestFd);

      ws.close();
      setCleaningProgress(100);
      setStatusMsg("Ingestion done!");

      // 2. Start reconciliation
      const reconFd = new FormData();
      reconFd.append("source_upload_id", uploadData.source_upload_id);
      reconFd.append("dest_upload_id", uploadData.dest_upload_id);
      reconFd.append("mapping", JSON.stringify(mappingData));
      reconFd.append("tol_amount", tolAmount);
      reconFd.append("tol_time", tolTime);
      const res = await axios.post(`${BASE}/reconcile_async`, reconFd);
      setJobId(res.data.job_id);
      setStep(4);
      setCleaningProgress(-1);
    } catch (e) {
      ws.close();
      setCleaningProgress(-1);
      setError(e.response?.data?.error || e.message || "Failed to start reconciliation");
    }
  };

  const STEPS = ["Upload Files", "Map Columns", "Tolerances", "Live Tracking"];

  return (
    <div>
      {/* Step indicator */}
      <div className="steps" style={{ marginBottom: 28 }}>
        {STEPS.map((label, i) => (
          <div key={i} className="step" style={{ alignItems: "center" }}>
            <div className={`step-circle ${step > i + 1 ? "done" : step === i + 1 ? "active" : ""}`}>
              {step > i + 1 ? "✓" : i + 1}
            </div>
            <span className={`step-label ${step === i + 1 ? "active" : step > i + 1 ? "done" : ""}`}>
              {label}
            </span>
            {i < STEPS.length - 1 && (
              <div className="step-line" style={{ flex: 1, margin: "0 8px", height: 2, background: step > i + 1 ? "var(--green)" : "var(--border)" }} />
            )}
          </div>
        ))}
      </div>

      {error && <div className="alert alert-red" style={{ marginBottom: 16 }}>{error}</div>}

      {step === 1 && <StepUpload onDone={handleUploadDone} />}
      {step === 2 && uploadData && <StepMapping uploadData={uploadData} onDone={handleMappingDone} initialMapping={initialMapping} />}
      {step === 3 && mapping && (
        <StepTolerances mapping={mapping} onDone={handleRunStart} />
      )}

      {cleaningProgress >= 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-body">
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6, fontSize: 13, color: "var(--text2)" }}>
              <span>{statusMsg || "Ingesting data..."}</span>
              <span>{cleaningProgress}%</span>
            </div>
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${cleaningProgress}%` }} />
            </div>
          </div>
        </div>
      )}

      {step === 4 && jobId && (
        <StepTracking
          runId={jobId}
          onViewResults={(id) => navigate("run-detail", { runId: Number(id) })}
        />
      )}
    </div>
  );
}
