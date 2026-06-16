export default function Topbar({ title, sub, navigate, page, isDark, onToggleTheme }) {
  return (
    <div className="topbar">
      <div>
        <span className="topbar-title">{title}</span>
        {sub && <span className="topbar-sub">— {sub}</span>}
      </div>

      <div className="topbar-actions">
        {page !== "test-run" && (
          <button className="btn btn-outline btn-sm" onClick={() => navigate("test-run")}>
            ⚡ Run Test
          </button>
        )}
        {page !== "new-run" && (
          <button className="btn btn-blue btn-sm" onClick={() => navigate("new-run")}>
            ✦ New Run
          </button>
        )}

        {/* Dark / Light Mode Toggle */}
        <button
          id="theme-toggle-btn"
          className="btn btn-outline btn-sm"
          onClick={onToggleTheme}
          title={isDark ? "Switch to Light Mode" : "Switch to Dark Mode"}
          style={{ fontSize: 15, padding: "5px 10px", lineHeight: 1 }}
        >
          {isDark ? "☀️" : "🌙"}
        </button>
      </div>
    </div>
  );
}
