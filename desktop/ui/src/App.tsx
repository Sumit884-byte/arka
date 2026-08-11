import { NavLink, Route, Routes } from "react-router-dom";
import ChatPage from "./pages/ChatPage";
import SkillsPage from "./pages/SkillsPage";
import StatusPage from "./pages/StatusPage";
import SettingsPanel from "./components/SettingsPanel";

export default function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="logo">A</div>
          <div>
            <h1>Arka</h1>
            <p className="sub">Local agent console</p>
          </div>
        </div>

        <div className="workspace-pill">
          <span>workspace</span>
          <code>local</code>
        </div>

        <nav className="nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Chat
          </NavLink>
          <NavLink to="/skills" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Skills
          </NavLink>
          <NavLink to="/status" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Status
          </NavLink>
        </nav>

        <SettingsPanel />

        <p className="sidebar-hint">
          Commands route to local skills on your machine. Token stays in this app unless you save it.
        </p>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<ChatPage />} />
          <Route path="/skills" element={<SkillsPage />} />
          <Route path="/status" element={<StatusPage />} />
        </Routes>
      </main>
    </div>
  );
}
