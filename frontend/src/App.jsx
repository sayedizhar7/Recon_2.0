import { useState, useEffect } from "react";
import Sidebar from "./layout/Sidebar";
import Topbar from "./layout/Topbar";
import Dashboard from "./pages/Dashboard";
import History from "./pages/History";
import RunDetail from "./pages/RunDetail";
import NewRun from "./pages/NewRun";
import TestRun from "./pages/TestRun";

export default function App() {
  const [page, setPage] = useState("dashboard");
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [mappingJson, setMappingJson] = useState(null);
  const [sourceUploadId, setSourceUploadId] = useState(null);
  const [destUploadId, setDestUploadId] = useState(null);

  // ── Dark / Light Mode ────────────────────────────────────────────────
  // Persisted in localStorage so preference survives page refresh.
  // Applied to document.body via data-theme attribute so CSS variables
  // in index.css can switch all colors instantly without JS-per-element.
  const [isDark, setIsDark] = useState(() => {
    const stored = localStorage.getItem("recon_theme");
    return stored !== "light"; // default dark
  });

  useEffect(() => {
    document.body.setAttribute("data-theme", isDark ? "dark" : "light");
    localStorage.setItem("recon_theme", isDark ? "dark" : "light");
  }, [isDark]);

  const handleToggleTheme = () => setIsDark((prev) => !prev);
  // ─────────────────────────────────────────────────────────────────────

  const navigate = (p, extras = {}) => {
    if (extras.runId !== undefined) setSelectedRunId(extras.runId);
    if (extras.mapping_json !== undefined) {
      setMappingJson(extras.mapping_json);
      setSourceUploadId(extras.source_upload_id || null);
      setDestUploadId(extras.dest_upload_id || null);
    } else if (p === "new-run") {
      setMappingJson(null);
      setSourceUploadId(null);
      setDestUploadId(null);
    }
    setPage(p);
  };

  const pageTitles = {
    dashboard: { title: "Dashboard", sub: "Overview & KPIs" },
    history: { title: "Run History", sub: "All reconciliation runs" },
    "run-detail": { title: `Run #${selectedRunId}`, sub: "Matched records & details" },
    "new-run": { title: "New Reconciliation", sub: "Upload files and run matching" },
    "test-run": { title: "Test Run", sub: "Test without saving to database" },
  };

  const currentMeta = pageTitles[page] || { title: "Recon 2.0", sub: "" };

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      <Sidebar currentPage={page} navigate={navigate} />

      <div className="main">
        <Topbar
          title={currentMeta.title}
          sub={currentMeta.sub}
          navigate={navigate}
          page={page}
          isDark={isDark}
          onToggleTheme={handleToggleTheme}
        />

        <div className="page-content">
          {page === "dashboard" && <Dashboard navigate={navigate} />}
          {page === "history" && <History navigate={navigate} />}
          {page === "run-detail" && <RunDetail runId={selectedRunId} navigate={navigate} />}
          {page === "new-run" && (
            <NewRun
              navigate={navigate}
              initialMapping={mappingJson}
              initialSourceUploadId={sourceUploadId}
              initialDestUploadId={destUploadId}
            />
          )}
          {page === "test-run" && <TestRun navigate={navigate} />}
        </div>
      </div>
    </div>
  );
}