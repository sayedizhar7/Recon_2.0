import { useEffect, useState } from "react";
import axios from "axios";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

const BASE = "http://localhost:8000";

const LAYER_COLORS = ["#4f8ef7", "#22c55e", "#f59e0b", "#a78bfa", "#22d3ee", "#ec4899"];
const LAYER_NAMES = ["Self Knock", "Exact Match", "Tolerance", "Subset", "Fuzzy", "LLM"];

function KPICard({ label, value, sub, color = "var(--primary)", icon }) {
  return (
    <div className="kpi-card">
      <div className="kpi-label">
        {icon && <span>{icon}</span>}
        {label}
      </div>
      <div className="kpi-value" style={{ color }}>{value ?? "—"}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

function StatusBadge({ status }) {
  const map = {
    completed: "badge-green",
    running: "badge-blue",
    failed: "badge-red",
  };
  return <span className={`badge ${map[status] || "badge-gray"}`}>{status}</span>;
}

export default function Dashboard({ navigate }) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchRuns();
  }, []);

  const fetchRuns = async () => {
    try {
      const res = await axios.get(`${BASE}/runs`);
      // Some servers may return an array or an object wrapper; normalize to an array
      const data = res && res.data ? res.data : [];
      if (Array.isArray(data)) setRuns(data);
      else if (data.runs && Array.isArray(data.runs)) setRuns(data.runs);
      else setRuns([]);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const totalRuns = runs.length;
  const totalMatched = runs.reduce((s, r) => s + (r.total_matched || 0), 0);
  const totalSrc = runs.reduce((s, r) => s + (r.total_source || 0), 0);
  const totalDest = runs.reduce((s, r) => s + (r.total_dest || 0), 0);
  const completed = runs.filter((r) => r.status === "completed").length;
  const matchRate = totalSrc > 0 ? ((totalMatched / totalSrc) * 100).toFixed(1) : 0;

  // Aggregate layer counts across all runs
  const layerData = LAYER_NAMES.map((name, i) => ({
    name,
    matches: runs.reduce((s, r) => s + (r[`layer${i}_count`] || 0), 0),
    color: LAYER_COLORS[i],
  }));

  const recentRuns = runs.slice(0, 8);

  if (loading) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">⟳</div>
        <div className="empty-state-text">Loading dashboard...</div>
      </div>
    );
  }

  return (
    <div>
      {/* KPI Cards */}
      <div className="kpi-grid">
        <KPICard label="Total Runs" value={totalRuns} icon="🔄" sub={`${completed} completed`} />
        <KPICard label="Source Records" value={totalSrc.toLocaleString()} icon="📥" color="var(--cyan)" />
        <KPICard label="Dest Records" value={totalDest.toLocaleString()} icon="📤" color="var(--purple)" />
        <KPICard label="Total Matched" value={totalMatched.toLocaleString()} icon="✓" color="var(--green)" />
        <KPICard label="Match Rate" value={`${matchRate}%`} icon="📊" color={matchRate >= 80 ? "var(--green)" : "var(--amber)"} sub="across all runs" />
      </div>

      {/* Layer Breakdown Chart */}
      {layerData.some((l) => l.matches > 0) && (
        <div className="card">
          <div className="card-header">
            <span style={{ fontSize: 16 }}>📈</span>
            <span className="card-title">Matches by Layer — All Runs</span>
          </div>
          <div className="card-body">
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={layerData} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
                <XAxis dataKey="name" tick={{ fill: "var(--text3)", fontSize: 11 }} />
                <YAxis tick={{ fill: "var(--text3)", fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8 }}
                  labelStyle={{ color: "var(--text)" }}
                  itemStyle={{ color: "var(--text2)" }}
                />
                <Bar dataKey="matches" radius={[4, 4, 0, 0]}>
                  {layerData.map((entry, index) => (
                    <Cell key={index} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Recent Runs Table */}
      <div className="card">
        <div className="card-header">
          <span style={{ fontSize: 16 }}>🕐</span>
          <span className="card-title">Recent Runs</span>
          <div className="card-actions">
            <button className="btn btn-outline btn-sm" onClick={() => navigate("history")}>
              View All →
            </button>
          </div>
        </div>

        {recentRuns.length === 0 ? (
          <div className="empty-state" style={{ padding: "40px 20px" }}>
            <div className="empty-state-icon">📂</div>
            <div className="empty-state-text">No runs yet</div>
            <div className="empty-state-sub">Click "New Run" to get started</div>
            <button
              className="btn btn-blue"
              style={{ marginTop: 16 }}
              onClick={() => navigate("new-run")}
            >
              ✦ Start First Run
            </button>
          </div>
        ) : (
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Source File</th>
                  <th>Dest File</th>
                  <th>Status</th>
                  <th>Source</th>
                  <th>Matched</th>
                  <th>Duration</th>
                  <th>Date</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {recentRuns.map((run) => (
                  <tr key={run.id}>
                    <td style={{ color: "var(--primary)", fontWeight: 600 }}>#{run.id}</td>
                    <td>{run.source_filename || "—"}</td>
                    <td>{run.dest_filename || "—"}</td>
                    <td><StatusBadge status={run.status} /></td>
                    <td>{(run.total_source || 0).toLocaleString()}</td>
                    <td style={{ color: "var(--green)", fontWeight: 600 }}>
                      {(run.total_matched || 0).toLocaleString()}
                    </td>
                    <td style={{ color: "var(--text3)" }}>
                      {run.total_duration_sec ? `${run.total_duration_sec}s` : "—"}
                    </td>
                    <td style={{ color: "var(--text3)" }}>
                      {run.created_at ? new Date(run.created_at).toLocaleDateString() : "—"}
                    </td>
                    <td>
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={() => navigate("run-detail", { runId: run.id })}
                      >
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}