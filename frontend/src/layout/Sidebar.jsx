const NAV = [
  {
    label: "Main",
    items: [
      { id: "dashboard", icon: "⊞", text: "Dashboard" },
      { id: "history", icon: "🕐", text: "History" },
    ],
  },
  {
    label: "Actions",
    items: [
      { id: "new-run", icon: "✦", text: "New Run" },
      { id: "test-run", icon: "⚡", text: "Test Run" },
    ],
  },
];

export default function Sidebar({ currentPage, navigate }) {
  return (
    <div className="sidebar">
      {/* Logo */}
      <div className="sidebar-logo">
        <div className="brand">
          <div className="logo-box">⟳</div>
          <div>
            <div className="brand-text">Recon 2.0</div>
            <div className="brand-sub">Reconciliation Engine</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      {NAV.map((section) => (
        <div key={section.label} className="nav-section">
          <span className="nav-label">{section.label}</span>
          {section.items.map((item) => (
            <div
              key={item.id}
              className={`nav-item${currentPage === item.id ? " active" : ""}`}
              onClick={() => navigate(item.id)}
            >
              <span className="ni">{item.icon}</span>
              <span>{item.text}</span>
            </div>
          ))}
        </div>
      ))}

      {/* User */}
      <div className="sidebar-user">
        <div className="user-info">
          <div className="user-avatar">A</div>
          <div>
            <div className="user-name">Admin</div>
            <div className="user-role">Reconciliation Manager</div>
          </div>
        </div>
      </div>
    </div>
  );
}
