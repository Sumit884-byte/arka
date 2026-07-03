import { useCallback, useEffect, useRef, useState } from "react";

const TOKEN_KEY = "arka_token";

type Role = "user" | "assistant";

interface Message {
  id: string;
  role: Role;
  content: string;
  error?: boolean;
  loading?: boolean;
  streaming?: boolean;
}

const QUICK_PROMPTS = [
  { label: "Weather today", text: "what's the weather today" },
  { label: "Where to invest", text: "where to invest" },
  { label: "Remind me in 1 hour", text: "remind me in 1 hour to drink water" },
  { label: "Summarize news", text: "summarize today's top news" },
];

function stripAnsi(text: string): string {
  return text.replace(/\x1b\[[0-9;]*m/g, "");
}

function formatLine(line: string): React.ReactNode {
  const trimmed = line.trimEnd();
  if (!trimmed) return "\n";

  if (/^#{1,2}\s/.test(trimmed)) {
    return (
      <div className="line-heading" key={trimmed}>
        {trimmed.replace(/^#+\s*/, "")}
      </div>
    );
  }
  if (/^#{3,4}\s/.test(trimmed)) {
    return (
      <div className="line-subheading" key={trimmed}>
        {trimmed.replace(/^#+\s*/, "")}
      </div>
    );
  }
  if (/^[-*•]\s/.test(trimmed)) {
    return <div className="line-bullet">{trimmed}</div>;
  }
  if (/disclaimer|not financial advice|for informational/i.test(trimmed)) {
    return <div className="line-disclaimer">{trimmed}</div>;
  }
  return trimmed + "\n";
}

function FormattedText({ text }: { text: string }) {
  const clean = stripAnsi(text).trim();
  const lines = clean.split("\n");
  return (
    <>
      {lines.map((line, i) => (
        <span key={i}>{formatLine(line)}</span>
      ))}
    </>
  );
}

async function consumeAgentStream(
  response: Response,
  onChunk: (text: string) => void,
): Promise<{ ok: boolean; output: string }> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";
  let full = "";
  let donePayload = { ok: false, output: "" };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      if (!part.trim()) continue;
      let event = "message";
      let data = "";
      for (const line of part.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) data = line.slice(5).trim();
      }
      if (!data) continue;
      const parsed = JSON.parse(data) as { text?: string; ok?: boolean; output?: string };
      if (event === "chunk" && parsed.text) {
        full += parsed.text;
        onChunk(parsed.text);
      } else if (event === "done") {
        donePayload = { ok: Boolean(parsed.ok), output: parsed.output || full };
      }
    }
  }
  return { ok: donePayload.ok, output: donePayload.output || full };
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M22 2L11 13" />
      <path d="M22 2L15 22L11 13L2 9L22 2Z" />
    </svg>
  );
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) ?? "");
  const [tokenDraft, setTokenDraft] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const r = await fetch("/v1/health");
        if (!cancelled) setOnline(r.ok);
      } catch {
        if (!cancelled) setOnline(false);
      }
    };
    check();
    const id = setInterval(check, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (!token) setShowSettings(true);
  }, [token]);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || busy) return;

      const tok = token.trim();
      if (!tok) {
        setShowSettings(true);
        return;
      }

      const userId = crypto.randomUUID();
      const assistantId = crypto.randomUUID();

      setMessages((prev) => [
        ...prev,
        { id: userId, role: "user", content: trimmed },
        { id: assistantId, role: "assistant", content: "", loading: true, streaming: true },
      ]);
      setInput("");
      setBusy(true);

      try {
        const r = await fetch("/v1/agent", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${tok}`,
            Accept: "text/event-stream",
          },
          body: JSON.stringify({ text: trimmed, remote_speak: false, stream: true }),
        });

        if (!r.ok) {
          let errMsg = r.statusText;
          try {
            const data = await r.json();
            errMsg =
              r.status === 401
                ? "Token rejected — use REMOTE_TOKEN from .env (must match what arka serve loaded)"
                : data.error || errMsg;
          } catch {
            if (r.status === 401) {
              errMsg = "Token rejected — check REMOTE_TOKEN in Settings";
            }
          }
          throw new Error(errMsg);
        }

        const result = await consumeAgentStream(r, (chunk) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + chunk } : m,
            ),
          );
        });

        const output = (result.output || "").trim() || "(no output)";
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  content: output,
                  loading: false,
                  streaming: false,
                  error: !result.ok,
                }
              : m,
          ),
        );
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Request failed";
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: msg, loading: false, streaming: false, error: true }
              : m,
          ),
        );
      } finally {
        setBusy(false);
        textareaRef.current?.focus();
      }
    },
    [busy, token],
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  };

  const saveToken = () => {
    const t = tokenDraft.trim();
    setToken(t);
    localStorage.setItem(TOKEN_KEY, t);
    setShowSettings(false);
  };

  const clearChat = () => setMessages([]);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="logo">⚡</span>
          <div>
            <h1>Arka</h1>
            <p>Your PC agent</p>
          </div>
        </div>

        <div className="sidebar-section">
          <label>Quick prompts</label>
          <div className="quick-prompts">
            {QUICK_PROMPTS.map((p) => (
              <button key={p.text} type="button" onClick={() => send(p.text)} disabled={busy}>
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div className="sidebar-footer">
          <span
            className={`status-dot ${online === true ? "online" : online === false ? "offline" : ""}`}
          />
          {online === null ? "Checking…" : online ? "Connected to PC" : "Server offline"}
          <br />
          <a href="/mobile" style={{ fontSize: "0.75rem" }}>
            Mobile voice UI →
          </a>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <span className="topbar-title">Chat</span>
          <div className="topbar-actions">
            <button type="button" onClick={clearChat}>
              Clear
            </button>
            <button type="button" onClick={() => { setTokenDraft(token); setShowSettings(true); }}>
              Settings
            </button>
          </div>
        </header>

        <div className="messages">
          {messages.length === 0 ? (
            <div className="empty-state">
              <div className="hero-icon">⚡</div>
              <h2>Ask Arka anything</h2>
              <p>
                Weather, investments, reminders, PDFs, YouTube summaries — your full agent runs on
                this PC. Type a message below or pick a quick prompt.
              </p>
            </div>
          ) : (
            messages.map((m) => (
              <div key={m.id} className={`message ${m.role}`}>
                <div className="message-role">{m.role === "user" ? "You" : "Arka"}</div>
                <div
                  className={`message-bubble${
                    m.loading && !m.content ? " loading" : ""
                  }${m.streaming ? " streaming" : ""}${m.error ? " error" : ""}${
                    m.loading && m.content ? " stream-cursor" : ""
                  }`}
                >
                  {m.loading && !m.content ? (
                    "Thinking…"
                  ) : m.loading ? (
                    stripAnsi(m.content)
                  ) : (
                    <FormattedText text={m.content} />
                  )}
                </div>
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="composer">
          <div className="composer-inner">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask Arka… (Enter to send, Shift+Enter for newline)"
              rows={1}
              disabled={busy}
            />
            <button
              type="button"
              className="send-btn"
              onClick={() => send(input)}
              disabled={busy || !input.trim()}
              title="Send"
            >
              <SendIcon />
            </button>
          </div>
        </div>
      </main>

      {showSettings && (
        <div className="modal-backdrop" onClick={() => token && setShowSettings(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Access token</h2>
            <p>
              Run <code>arka serve</code> on your PC and paste <code>REMOTE_TOKEN</code> from
              your <code>.env</code> (or the token printed in the terminal). Saved in this
              browser only.
            </p>
            <input
              type="password"
              value={tokenDraft}
              onChange={(e) => setTokenDraft(e.target.value)}
              placeholder="REMOTE_TOKEN"
              autoFocus
              onKeyDown={(e) => e.key === "Enter" && saveToken()}
            />
            <div className="modal-actions">
              {token && (
                <button type="button" className="secondary" onClick={() => setShowSettings(false)}>
                  Cancel
                </button>
              )}
              <button type="button" className="primary" onClick={saveToken}>
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
