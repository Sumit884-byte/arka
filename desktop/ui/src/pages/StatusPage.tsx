import { useCallback, useEffect, useState } from "react";
import { fetchDoctor, fetchHealth, type DoctorResponse, type HealthResponse } from "../api/client";
import { CopyButtonWithFeedback } from "../components/ui/CopyButton";
import TopBar from "../components/TopBar";

export default function StatusPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [doctor, setDoctor] = useState<DoctorResponse | null>(null);
  const [loadingHealth, setLoadingHealth] = useState(true);
  const [loadingDoctor, setLoadingDoctor] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadHealth = useCallback(async () => {
    setLoadingHealth(true);
    setError(null);
    try {
      const data = await fetchHealth();
      setHealth(data);
      if (!data.ok) {
        setError(data.error || "Backend health check failed.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Backend unreachable.");
      setHealth({ ok: false });
    } finally {
      setLoadingHealth(false);
    }
  }, []);

  useEffect(() => {
    void loadHealth();
  }, [loadHealth]);

  async function runDoctor() {
    setLoadingDoctor(true);
    setError(null);
    try {
      const data = await fetchDoctor();
      setDoctor(data);
      if (!data.ok && data.error) {
        setError(data.error);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Doctor check failed.");
    } finally {
      setLoadingDoctor(false);
    }
  }

  const status = loadingHealth ? "Checking…" : health?.ok ? "Online" : "Offline";

  return (
    <div className="page">
      <TopBar
        title="Status"
        branch=""
        subtitle=""
        status={status}
        statusError={!loadingHealth && !health?.ok}
      />

      <div className="page-body">
        {error ? <div className="error-banner">{error}</div> : null}

        <section className="panel status-card">
          <h2>Backend</h2>
          <dl>
            <div>
              <dt>Health</dt>
              <dd>{health?.ok ? "OK" : "Unavailable"}</dd>
            </div>
            <div>
              <dt>Agent</dt>
              <dd>{health?.agent || "—"}</dd>
            </div>
            <div>
              <dt>Speak language</dt>
              <dd>{health?.speak_lang || "—"}</dd>
            </div>
          </dl>
          <button type="button" className="btn" onClick={() => void loadHealth()} disabled={loadingHealth}>
            Refresh health
          </button>
        </section>

        <section className="panel status-card">
          <div className="status-card-head">
            <h2>Doctor</h2>
            <button type="button" className="btn primary" onClick={() => void runDoctor()} disabled={loadingDoctor}>
              {loadingDoctor ? "Running…" : "Run doctor"}
            </button>
          </div>
          <p className="muted" style={{ marginTop: 0 }}>
            Full install and API-key check from <code>arka doctor</code> (local bridge endpoint).
          </p>
          {doctor?.output ? (
            <div className="doctor-output-wrap">
              <pre className="doctor-output">{doctor.output}</pre>
              <CopyButtonWithFeedback text={doctor.output} label="Doctor output copied" />
            </div>
          ) : (
            <p className="muted">Run doctor to see setup diagnostics.</p>
          )}
        </section>
      </div>
    </div>
  );
}
