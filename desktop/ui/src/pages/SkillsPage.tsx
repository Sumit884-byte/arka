import { useEffect, useMemo, useState } from "react";
import Fuse from "fuse.js";
import { Search } from "lucide-react";
import { fetchCapabilities } from "../api/client";
import TopBar from "../components/TopBar";

export default function SkillsPage() {
  const [skills, setSkills] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchCapabilities()
      .then((data) => {
        if (!active) return;
        if (!data.ok) {
          setError(data.error || "Could not load skills.");
          return;
        }
        setSkills(data.dispatch_skills || []);
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Could not load skills.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const fuse = useMemo(
    () =>
      new Fuse(skills, {
        threshold: 0.35,
        ignoreLocation: true,
      }),
    [skills],
  );

  const filtered = useMemo(() => {
    const q = query.trim();
    if (!q) return skills;
    return fuse.search(q).map((result) => result.item);
  }, [query, skills, fuse]);

  const status = loading ? "Loading…" : error ? "Error" : "Ready";

  return (
    <div className="page">
      <TopBar
        title="Skills"
        branch=""
        subtitle=""
        status={status}
        statusError={Boolean(error)}
        actions={<span className="chip">{skills.length} dispatch skills</span>}
      />

      <div className="page-body">
        {error ? <div className="error-banner">{error}</div> : null}

        <div className="panel skills-panel">
          <div className="skills-toolbar">
            <div className="search-field">
              <Search size={16} strokeWidth={2} className="search-icon" aria-hidden="true" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter skills…"
                aria-label="Filter skills"
              />
            </div>
            <p className="muted" style={{ margin: 0, fontSize: "0.84rem" }}>
              Loaded from local dispatch modules · {filtered.length} shown
            </p>
          </div>

          {loading ? (
            <p className="muted">Loading skills…</p>
          ) : (
            <div className="skill-grid">
              {filtered.map((skill) => (
                <div key={skill} className="skill-card">
                  <code>{skill}</code>
                </div>
              ))}
              {!filtered.length ? <p className="muted">No skills match your filter.</p> : null}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
