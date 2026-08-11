import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import {
  askAgent,
  fetchDesktopConfig,
  fetchSessionHistory,
  getApiToken,
  resetChatId,
  resetSessionHistory,
  type AgentResponse,
  type SessionTurn,
} from "../api/client";
import TopBar from "../components/TopBar";
import { ComposerBar, MessageBubble, SuggestionCard, Trash2, TypingIndicator } from "../components/ui";
import { chatSuggestions } from "../constants/suggestions";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  routeSkill?: string;
  ok?: boolean;
};

function turnToMessage(turn: SessionTurn, index: number): ChatMessage | null {
  const role = turn.role === "assistant" ? "assistant" : turn.role === "user" ? "user" : null;
  const text = turn.text.trim();
  if (!role || !text) return null;
  return {
    id: turn.ts ? `turn-${turn.ts}` : `turn-${index}`,
    role,
    text,
    ok: role === "assistant" ? true : undefined,
  };
}

export default function ChatPage() {
  const location = useLocation();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [envToken, setEnvToken] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    fetchDesktopConfig()
      .then((cfg) => setEnvToken(Boolean(cfg.has_token)))
      .catch(() => {});
  }, []);

  const send = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    if (!getApiToken()) {
      try {
        const cfg = await fetchDesktopConfig();
        if (!cfg.has_token) {
          setError("Add your REMOTE_TOKEN in the sidebar before sending commands.");
          return;
        }
      } catch {
        setError("Add your REMOTE_TOKEN in the sidebar before sending commands.");
        return;
      }
    }

    setError(null);
    setBusy(true);
    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", text: trimmed };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");

    try {
      const response: AgentResponse = await askAgent(trimmed);
      const assistant: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        text: response.output?.trim() || response.error || "No output returned.",
        routeSkill: response.route?.skill,
        ok: response.ok,
      };
      setMessages((prev) => [...prev, assistant]);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Request failed.";
      setError(message);
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "assistant", text: message, ok: false },
      ]);
    } finally {
      setBusy(false);
      listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [busy]);

  useEffect(() => {
    let active = true;
    async function loadHistory() {
      setLoadingHistory(true);
      try {
        const response = await fetchSessionHistory();
        if (!active) return;
        const restored = (response.turns || [])
          .map(turnToMessage)
          .filter((message): message is ChatMessage => message !== null);
        setMessages(restored);
      } catch {
        if (active) {
          setMessages([]);
        }
      } finally {
        if (active) {
          setLoadingHistory(false);
        }
      }
    }
    void loadHistory();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const prompt = (location.state as { prompt?: string } | null)?.prompt;
    if (prompt && !loadingHistory && !busy) {
      void send(prompt);
      window.history.replaceState({}, document.title);
    }
  }, [location.state, loadingHistory, busy, send]);

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [input]);

  const hasToken = useMemo(() => Boolean(getApiToken()) || envToken, [messages, busy, envToken]);
  const hasMessages = messages.length > 0 || busy;

  const statusLabel = busy
    ? "Thinking…"
    : error
      ? "Error"
      : loadingHistory
        ? "Loading…"
        : hasToken
          ? "Ready"
          : "Token required";

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send(input);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send(input);
    }
  }

  async function clearHistory() {
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await resetSessionHistory();
      resetChatId();
      setMessages([]);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not clear history.";
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page chat-page">
      <TopBar
        status={statusLabel}
        statusError={Boolean(error) && !busy}
        actions={
          messages.length > 0 ? (
            <button type="button" className="btn btn-icon-text" onClick={() => void clearHistory()} disabled={busy}>
              <Trash2 size={15} strokeWidth={2} />
              Clear
            </button>
          ) : null
        }
      />

      <div className={`chat-body ${hasMessages ? "has-messages" : ""}`} ref={listRef}>
        {error ? <div className="error-banner">{error}</div> : null}

        {loadingHistory ? (
          <section className="chat-empty">
            <p className="muted">Loading conversation from Arka…</p>
          </section>
        ) : messages.length === 0 ? (
          <motion.section
            className="chat-empty"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35 }}
          >
            <p className="eyebrow">Ask in plain English</p>
            <h2>What should Arka do next?</h2>
            <p className="muted">
              Commands route to local skills — charts, repo tools, reminders, and more.
            </p>
            <div className="codex-card">
              <div className="codex-card-header">
                <span>session</span>
                <span>ready</span>
              </div>
              <div className="terminal-line">
                <span>›</span> arka ask "what is Rust?"
              </div>
              <div className="terminal-line">
                <span>›</span> routed to web + AI · zero tokens on symbolic match
              </div>
              <div className="terminal-line">
                <span>›</span> 70+ local skills on your machine
              </div>
            </div>
            <div className="suggestions">
              {chatSuggestions.map((item) => (
                <SuggestionCard
                  key={item.title}
                  title={item.title}
                  body={item.body}
                  disabled={busy}
                  onClick={() => void send(item.body)}
                />
              ))}
            </div>
          </motion.section>
        ) : (
          <div className="messages">
            {messages.map((message) => (
              <MessageBubble
                key={message.id}
                role={message.role}
                text={message.text}
                routeSkill={message.routeSkill}
              />
            ))}
            {busy ? (
              <motion.div
                className="msg arka"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <div className="avatar arka">A</div>
                <div className="bubble">
                  <TypingIndicator />
                </div>
              </motion.div>
            ) : null}
          </div>
        )}
      </div>

      <ComposerBar
        inputRef={inputRef}
        value={input}
        busy={busy}
        onChange={setInput}
        onSubmit={onSubmit}
        onKeyDown={onKeyDown}
      />
    </div>
  );
}
