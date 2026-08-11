import type { ReactNode } from "react";

type TopBarProps = {
  title?: string;
  branch?: string;
  subtitle?: string;
  status: string;
  statusError?: boolean;
  actions?: ReactNode;
};

export default function TopBar({
  title = "Arka",
  branch = "local / desktop",
  subtitle = "route · skills · voice",
  status,
  statusError = false,
  actions,
}: TopBarProps) {
  return (
    <header className="topbar">
      <div className="top-title">
        <strong>{title}</strong>
        {branch ? <span className="branch">{branch}</span> : null}
        {subtitle ? <span className="top-sub">{subtitle}</span> : null}
      </div>
      <div className="topbar-right">
        {actions}
        <div className="status">
          <span className={`dot ${statusError ? "err" : ""}`} />
          {status}
        </div>
      </div>
    </header>
  );
}
