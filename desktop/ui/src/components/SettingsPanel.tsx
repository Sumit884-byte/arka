import { useEffect, useState } from "react";
import { fetchDesktopConfig, getApiToken, setApiToken } from "../api/client";

export default function SettingsPanel() {
  const [token, setToken] = useState(getApiToken());
  const [saved, setSaved] = useState(false);
  const [desktop, setDesktop] = useState(false);
  const [envToken, setEnvToken] = useState(false);

  useEffect(() => {
    setToken(getApiToken());
    fetchDesktopConfig()
      .then((cfg) => {
        setDesktop(cfg.app === "desktop");
        setEnvToken(Boolean(cfg.has_token));
      })
      .catch(() => {});
  }, []);

  function save() {
    setApiToken(token);
    setSaved(true);
    window.setTimeout(() => setSaved(false), 1500);
  }

  return (
    <section className="panel settings">
      {desktop ? (
        <p className="muted" style={{ margin: "0 0 10px", fontSize: "0.78rem" }}>
          Desktop mode — Arka runs locally on your machine.
        </p>
      ) : null}
      <div className="label">API token</div>
      <input
        type="password"
        value={token}
        onChange={(event) => setToken(event.target.value)}
        placeholder="REMOTE_TOKEN from .env"
        autoComplete="off"
      />
      <button type="button" className="btn primary" onClick={save}>
        Save token
      </button>
      <p className="muted" style={{ margin: 0, fontSize: "0.78rem", lineHeight: 1.45 }}>
        {saved
          ? "Saved."
          : envToken && !token
            ? "Token loaded from ~/.config/arka/.env — chat works without saving."
            : "Required for chat unless REMOTE_TOKEN is in your Arka .env."}
      </p>
    </section>
  );
}
