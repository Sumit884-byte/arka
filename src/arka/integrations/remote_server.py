#!/usr/bin/env python3
"""Remote Arka server — phone does STT/TTS; PC runs the heavy agent."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shlex
import signal
import subprocess
import sys
import contextlib
import io
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

CACHE = Path.home() / ".cache" / "fish-agent"
PID_PATH = CACHE / "arka_remote.pid"
UPLOAD_DIR = CACHE / "remote-uploads"
REMOTE_REPOS_DIR = CACHE / "remote-repos"
MAX_MEDIA_UPLOAD_BYTES = int(os.environ.get("ARKA_REMOTE_UPLOAD_MAX_BYTES", str(16 * 1024 * 1024)))
CODING_ALLOWED_SKILLS = {
    "ci",
    "code",
    "dev_doctor",
    "dev_tools",
    "doctor",
    "github_actions",
    "github_repo",
    "hooks",
    "lint_project",
    "plugin",
    "plugins",
    "pr_check",
    "repo",
    "repo_context",
    "repo_graph",
    "repo_health",
    "repo_map",
    "review",
    "route_audit",
    "security",
    "skill",
    "structure",
    "workspace",
}
_GITHUB_REPO_RE = re.compile(r"https?://github\.com/([^/\s#?]+)/([^/\s#?]+)", re.I)
_GITHUB_INIT_RE = re.compile(
    r"(?i)\b(?:init|initialize|clone|open|use|connect|setup|set\s+up|load)\b.*\bgithub\b|"
    r"\bgithub\b.*\b(?:repo|repository|project|workspace|code\s+project)\b"
)


@dataclass(frozen=True)
class RemoteRepo:
    owner: str
    repo: str
    url: str
    path: Path


def _bootstrap_env() -> None:
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass

MOBILE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0b0d12">
<title>Arka Codex Demo</title>
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<style>
  :root {
    color-scheme:dark;
    --bg:#0b0d12; --panel:#11141b; --panel-soft:#191d27; --panel-raised:#1f2430; --text:#f4f4f5;
    --muted:#9ca3af; --line:#2b3140; --accent:#f97316; --accent-2:#fb923c;
    --ok:#22c55e; --err:#f87171; --shadow:0 28px 90px rgba(0,0,0,.38); --glow:rgba(249,115,22,.11);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg:#0b0d12; --panel:#11141b; --panel-soft:#191d27; --panel-raised:#1f2430; --text:#f4f4f5;
      --muted:#9ca3af; --line:#2b3140; --accent:#f97316; --accent-2:#fb923c;
      --ok:#22c55e; --err:#f87171; --shadow:0 28px 90px rgba(0,0,0,.38); --glow:rgba(249,115,22,.11);
    }
  }
  * { box-sizing:border-box; }
  html, body, #root { min-height:100dvh; }
  body { margin:0; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:
    radial-gradient(circle at 62% -12%, var(--glow), transparent 34rem),
    linear-gradient(135deg, rgba(255,255,255,.025), transparent 28rem), var(--bg); color:var(--text); }
  button, input, textarea { font:inherit; }
  .app { min-height:100dvh; display:grid; grid-template-columns:272px 1fr; }
  .sidebar { border-right:1px solid var(--line); background:rgba(12,15,22,.78); padding:14px; display:flex; flex-direction:column; gap:12px; backdrop-filter:blur(18px); }
  .brand { display:flex; align-items:center; gap:12px; }
  .logo { width:34px; height:34px; border-radius:10px; display:grid; place-items:center; color:#0b0d12; font-weight:900; background:linear-gradient(135deg,#f97316,#fbbf24); box-shadow:0 12px 30px rgba(249,115,22,.22); }
  h1 { font-size:1rem; margin:0; letter-spacing:-.02em; }
  .sub { color:var(--muted); font-size:.82rem; margin:.12rem 0 0; line-height:1.35; }
  .workspace-pill { border:1px solid var(--line); border-radius:12px; padding:8px 10px; color:var(--muted); background:rgba(255,255,255,.025); font-size:.78rem; display:flex; justify-content:space-between; gap:8px; }
  .workspace-pill code { color:#e5e7eb; font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
  .panel { border:1px solid var(--line); background:linear-gradient(180deg, rgba(255,255,255,.035), rgba(255,255,255,.012)); border-radius:16px; box-shadow:var(--shadow); }
  .token { padding:14px; display:grid; gap:10px; }
  .label { font-size:.76rem; color:var(--muted); font-weight:700; text-transform:uppercase; letter-spacing:.08em; }
  input { width:100%; border:1px solid var(--line); border-radius:12px; background:#0d1118; color:var(--text); padding:11px 12px; outline:none; }
  input:focus, textarea:focus { border-color:color-mix(in srgb, var(--accent) 68%, var(--line)); box-shadow:0 0 0 4px rgba(249,115,22,.12); }
  .side-actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
  .btn { border:1px solid var(--line); background:#151a24; color:var(--text); border-radius:12px; padding:10px 12px; cursor:pointer; transition:.15s ease; }
  .btn:hover { transform:translateY(-1px); border-color:color-mix(in srgb, var(--accent) 40%, var(--line)); }
  .btn.primary { background:var(--accent); color:#111827; border-color:var(--accent); font-weight:750; }
  .btn.primary:hover { background:var(--accent-2); }
  .chips { display:flex; flex-direction:column; gap:8px; }
  .chip { text-align:left; border:1px solid transparent; background:transparent; color:var(--text); border-radius:12px; padding:10px 11px; cursor:pointer; line-height:1.3; }
  .chip:hover { border-color:var(--line); background:rgba(255,255,255,.04); }
  .chip small { display:block; color:var(--muted); margin-top:2px; }
  .hint { color:var(--muted); font-size:.78rem; line-height:1.45; margin-top:auto; }
  .main { min-width:0; display:flex; flex-direction:column; }
  .topbar { height:58px; border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; padding:0 22px; background:rgba(11,13,18,.72); position:sticky; top:0; z-index:2; backdrop-filter:blur(18px); }
  .top-title { display:flex; align-items:center; gap:10px; min-width:0; }
  .branch { border:1px solid var(--line); border-radius:999px; padding:4px 8px; color:var(--muted); font-size:.76rem; font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
  .status { color:var(--muted); font-size:.86rem; display:flex; align-items:center; gap:8px; }
  .dot { width:9px; height:9px; border-radius:50%; background:var(--ok); box-shadow:0 0 0 4px rgba(34,197,94,.12); }
  .dot.err { background:var(--err); box-shadow:0 0 0 4px rgba(220,38,38,.12); }
  .chat { flex:1; overflow:auto; padding:28px 18px 170px; transition:padding .18s ease; }
  .chat.has-messages { padding-top:46px; }
  .empty { max-width:780px; margin:7vh auto 0; text-align:left; }
  .eyebrow { color:var(--accent-2); font-size:.82rem; font-weight:800; letter-spacing:.08em; text-transform:uppercase; margin-bottom:12px; }
  .empty h2 { font-size:clamp(2rem,5vw,3.25rem); line-height:1.02; letter-spacing:-.06em; margin:0 0 14px; text-wrap:balance; }
  .empty p { color:var(--muted); margin:0 auto 24px; max-width:560px; line-height:1.55; }
  .suggestions { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; max-width:760px; margin:0 auto; }
  .suggestion { border:1px solid var(--line); background:linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.018)); color:var(--text); border-radius:16px; padding:16px; text-align:left; cursor:pointer; min-height:86px; transition:.16s ease; }
  .suggestion:hover { transform:translateY(-2px); border-color:color-mix(in srgb, var(--accent) 45%, var(--line)); box-shadow:0 18px 45px rgba(0,0,0,.12); }
  .suggestion b { display:block; margin-bottom:6px; color:var(--text); }
  .suggestion span { color:var(--muted); font-size:.9rem; line-height:1.4; }
  .media-note { max-width:760px; margin:18px auto 0; color:var(--muted); font-size:.86rem; line-height:1.45; }
  .codex-card { max-width:760px; margin:0 0 20px; border:1px solid var(--line); border-radius:18px; background:#0d1118; padding:14px; box-shadow:var(--shadow); }
  .codex-card-header { color:var(--muted); font-size:.78rem; display:flex; justify-content:space-between; margin-bottom:10px; font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
  .terminal-line { font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; color:#d1d5db; line-height:1.7; }
  .terminal-line span { color:var(--accent-2); }
  .messages { max-width:760px; min-height:calc(100dvh - 260px); margin:0 auto; display:flex; flex-direction:column; gap:20px; justify-content:flex-start; }
  .msg { display:grid; grid-template-columns:38px minmax(0,1fr); gap:12px; align-items:start; }
  .msg.user { grid-template-columns:minmax(0,1fr) 38px; }
  .msg.user .avatar { grid-column:2; grid-row:1; }
  .msg.user .bubble { grid-column:1; grid-row:1; justify-self:end; max-width:min(620px, 100%); }
  .avatar { width:38px; height:38px; border-radius:14px; display:grid; place-items:center; background:var(--panel-soft); border:1px solid var(--line); font-weight:800; }
  .avatar.arka { background:linear-gradient(135deg,#10a37f,#34d399); color:#fff; border:none; }
  .bubble { background:var(--panel); border:1px solid var(--line); border-radius:18px; padding:14px 16px; line-height:1.5; white-space:pre-wrap; overflow:auto; overflow-wrap:anywhere; box-shadow:0 8px 30px rgba(15,23,42,.04); }
  .bubble.user { background:var(--panel-soft); }
  .composer-wrap { position:fixed; left:272px; right:0; bottom:0; padding:18px; background:linear-gradient(to top,var(--bg) 74%,transparent); }
  .attachments { max-width:880px; margin:0 auto 10px; display:flex; flex-wrap:wrap; gap:8px; }
  .attachment { border:1px solid var(--line); background:var(--panel); border-radius:999px; padding:8px 10px; display:flex; align-items:center; gap:8px; color:var(--muted); font-size:.84rem; }
  .attachment button { border:0; background:transparent; color:var(--muted); cursor:pointer; padding:0 2px; }
  .composer { max-width:880px; margin:0 auto; background:rgba(17,20,27,.92); border:1px solid #3b4354; border-radius:18px; box-shadow:var(--shadow); padding:10px; display:grid; grid-template-columns:auto 1fr auto auto; gap:8px; align-items:end; backdrop-filter:blur(18px); }
  textarea { min-height:48px; max-height:180px; resize:none; border:0; background:transparent; color:var(--text); outline:none; padding:12px; line-height:1.45; }
  .round { width:48px; height:48px; border-radius:14px; border:1px solid var(--line); display:grid; place-items:center; cursor:pointer; background:var(--panel-soft); color:var(--text); }
  .hidden-file { display:none; }
  .round.send { background:var(--accent); color:#111827; border-color:var(--accent); font-weight:900; }
  .round.listening { background:var(--err); color:#fff; animation:pulse 1s infinite; }
  .fineprint { max-width:880px; margin:8px auto 0; color:var(--muted); font-size:.76rem; text-align:center; }
  @keyframes pulse { 50% { transform:scale(1.05); } }
  @media (max-width:840px) {
    .app { grid-template-columns:1fr; }
    .sidebar { display:none; }
    .composer-wrap { left:0; }
    .topbar { padding:0 14px; gap:10px; }
    .topbar .sub { display:none; }
    .branch { font-size:.72rem; padding:3px 7px; white-space:nowrap; }
    .status { font-size:.8rem; white-space:nowrap; }
    .suggestions { grid-template-columns:1fr; }
    .chat { padding:26px 18px 240px; }
    .chat.has-messages { padding-top:24px; }
    .empty { margin-top:5vh; }
    .empty h2 { font-size:2rem; letter-spacing:-.045em; }
    .empty p { font-size:.96rem; }
    .composer-wrap { padding:14px; }
    .composer { grid-template-columns:46px minmax(0,1fr) 46px 46px; border-radius:22px; }
    .round { width:46px; height:46px; border-radius:15px; }
    .fineprint { max-width:340px; }
    .messages { min-height:calc(100dvh - 250px); }
    .msg, .msg.user { grid-template-columns:1fr; }
    .msg .avatar, .msg.user .avatar { display:none; }
    .msg.user .bubble { grid-column:1; max-width:92%; }
  }
</style>
</head>
<body>
<div id="root"></div>
<script type="text/babel">
const {useEffect, useMemo, useRef, useState} = React;
window.__arkaUiErrors = [];
window.addEventListener("error", (event) => {
  window.__arkaUiErrors.push(event.message || String(event.error || "unknown UI error"));
});
window.addEventListener("unhandledrejection", (event) => {
  window.__arkaUiErrors.push(event.reason?.message || String(event.reason || "unknown promise rejection"));
});
const examples = [
  ["Init a GitHub repo", "Paste a repo URL and make it the workspace."],
  ["Run CI gates", "Execute hosted-safe verification."],
  ["Review staged diff", "Summarize risk, tests, and next fix."],
  ["Analyze media evidence", "Upload screenshots, recordings, logs, or docs."]
];

function speak(text) {
  if (!text || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = localStorage.getItem("arka_speak_lang") || "en-IN";
  window.speechSynthesis.speak(u);
}

function App() {
  const [token, setToken] = useState(localStorage.getItem("arka_token") || "");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState("Ready");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [attachments, setAttachments] = useState([]);
  const endRef = useRef(null);
  const fileRef = useRef(null);
  const inputRef = useRef(null);
  const recognitionRef = useRef(null);
  const speechSupported = useMemo(() => Boolean(window.SpeechRecognition || window.webkitSpeechRecognition), []);
  const hasMessages = messages.length > 0 || busy;

  useEffect(() => {
    endRef.current?.scrollIntoView({behavior: "smooth"});
  }, [messages, busy]);
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = Math.min(el.scrollHeight, 132) + "px";
  }, [input]);

  function saveToken() {
    localStorage.setItem("arka_token", token.trim());
    setStatus("Token saved locally");
  }

  function clearChat() {
    setMessages([]);
    setAttachments([]);
    setStatus("Cleared");
  }

  function addFiles(files) {
    const picked = Array.from(files || []);
    if (!picked.length) return;
    const next = picked.map((file) => ({
      id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now() + Math.random()),
      file,
      name: file.name,
      type: file.type || "application/octet-stream",
      size: file.size
    }));
    setAttachments((items) => [...items, ...next]);
    setStatus(`${next.length} file${next.length === 1 ? "" : "s"} attached`);
  }

  function removeAttachment(id) {
    setAttachments((items) => items.filter((item) => item.id !== id));
  }

  function fileToDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(reader.error || new Error("Could not read file"));
      reader.readAsDataURL(file);
    });
  }

  async function uploadAttachments(tok) {
    const uploaded = [];
    for (const item of attachments) {
      const dataUrl = await fileToDataUrl(item.file);
      const base64 = dataUrl.includes(",") ? dataUrl.split(",", 2)[1] : dataUrl;
      const r = await fetch("/v1/media", {
        method: "POST",
        headers: {"Content-Type": "application/json", "Authorization": "Bearer " + tok},
        body: JSON.stringify({name: item.name, type: item.type, data: base64})
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `upload failed for ${item.name}`);
      uploaded.push(data.media);
    }
    return uploaded;
  }

  async function askArka(text = input) {
    const prompt = text.trim();
    const tok = token.trim() || localStorage.getItem("arka_token") || "";
    if ((!prompt && attachments.length === 0) || busy) return;
    if (!tok) {
      setStatus("Enter the demo access token first");
      return;
    }
    setInput("");
    setBusy(true);
    setStatus(attachments.length ? "Uploading media…" : "Thinking…");
    const userText = prompt || "Please analyze the attached media.";
    setMessages((items) => [...items, {role: "user", text: userText, attachments: attachments.map((a) => a.name)}]);
    try {
      const uploaded = await uploadAttachments(tok);
      const mediaContext = uploaded.length
        ? "\\n\\nAttached media available to Arka:\\n" + uploaded.map((m, index) =>
            `${index + 1}. ${m.name} (${m.type}, ${m.bytes} bytes) saved at ${m.path}`
          ).join("\\n")
        : "";
      setStatus("Thinking…");
      const r = await fetch("/v1/agent", {
        method: "POST",
        headers: {"Content-Type": "application/json", "Authorization": "Bearer " + tok},
        body: JSON.stringify({text: userText + mediaContext, remote_speak: true, media: uploaded})
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || r.statusText);
      const answer = (data.output || "").trim() || "(No output)";
      setMessages((items) => [...items, {role: "arka", text: String(answer), ok: Boolean(data.ok), profile: data.profile || ""}]);
      setAttachments([]);
      setStatus(data.ok ? "Done" : "Finished with errors");
      if (data.speak_text) speak(data.speak_text);
    } catch (err) {
      setMessages((items) => [...items, {role: "arka", text: "Error: " + err.message, ok: false}]);
      setStatus("Error");
    } finally {
      setBusy(false);
    }
  }

  function startListen() {
    if (!speechSupported || listening) return;
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new SR();
    recognitionRef.current = rec;
    rec.lang = localStorage.getItem("arka_stt_lang") || "en-IN";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = (ev) => {
      const text = ev.results[0][0].transcript.trim();
      if (text) askArka(text);
    };
    rec.onerror = (ev) => {
      setStatus(ev.error || "Speech error");
      setListening(false);
    };
    rec.onend = () => setListening(false);
    setListening(true);
    setStatus("Listening…");
    rec.start();
  }

  function stopListen() {
    recognitionRef.current?.stop();
    setListening(false);
  }

  function onKeyDown(ev) {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      askArka();
    }
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="logo">A</div>
          <div>
            <h1>Arka Codex</h1>
            <p className="sub">Hosted coding agent console</p>
          </div>
        </div>
        <div className="workspace-pill"><span>workspace</span><code>/demo</code></div>
        <div className="panel token">
          <div className="label">Demo access</div>
          <input type="password" placeholder="REMOTE_TOKEN" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
          <div className="side-actions">
            <button className="btn primary" onClick={saveToken}>Save</button>
            <button className="btn" onClick={clearChat}>Clear</button>
          </div>
        </div>
        <div className="chips">
          {examples.map(([title, subtitle]) => (
            <button className="chip" key={title} onClick={() => askArka(title)}>
              {title}<small>{subtitle}</small>
            </button>
          ))}
        </div>
        <p className="hint">The access token stays in this browser. Uploads are sent only after you press send, then passed to Arka as concrete file paths and metadata.</p>
      </aside>
      <main className="main">
        <div className="topbar">
          <div className="top-title">
            <strong>Arka</strong>
            <span className="branch">hosted / coding</span>
            <span className="sub">inspect · test · review · route</span>
          </div>
          <div className="status"><span className={"dot " + (status === "Error" ? "err" : "")}></span>{status}</div>
        </div>
        <section className={"chat " + (hasMessages ? "has-messages" : "")}>
          {!hasMessages ? (
            <div className="empty">
              <div className="eyebrow">AI coding workspace</div>
              <h2>Ask Arka to inspect, test, or improve a project.</h2>
              <p>Paste a GitHub repo URL to initialize a hosted workspace, or attach screenshots, videos, audio, PDFs, logs, JSON, markdown, or source files. Arka receives concrete repo/file evidence, then routes to hosted-safe coding skills instead of generic advice.</p>
              <div className="codex-card">
                <div className="codex-card-header"><span>session</span><span>ready</span></div>
                <div className="terminal-line"><span>›</span> init https://github.com/org/repo as a workspace</div>
                <div className="terminal-line"><span>›</span> Arka routes to CI, review, repo health, or media analysis</div>
                <div className="terminal-line"><span>›</span> review outputs before applying production changes</div>
              </div>
              <div className="suggestions">
                {examples.map(([title, subtitle]) => (
                  <button className="suggestion" key={title} onClick={() => askArka(title)}>
                    <b>{title}</b><span>{subtitle}</span>
                  </button>
                ))}
              </div>
              <p className="media-note">For judge demos: share a token privately, upload a screenshot or recording, then ask Arka to find visual bugs, summarize reproduction steps, or propose a focused fix.</p>
            </div>
          ) : (
            <div className="messages">
              {messages.map((m, i) => (
                <div className={"msg " + (m.role === "user" ? "user" : "arka")} key={i}>
                  <div className={"avatar " + (m.role === "arka" ? "arka" : "")}>{m.role === "arka" ? "A" : "You".slice(0,1)}</div>
                  <div className={"bubble " + (m.role === "user" ? "user" : "")}>
                    {String(m.text || "")}
                    {m.attachments?.length ? "\\n\\n" + m.attachments.map((name) => `📎 ${name}`).join("\\n") : ""}
                  </div>
                </div>
              ))}
              {busy && <div className="msg"><div className="avatar arka">A</div><div className="bubble">Thinking through the safest route…</div></div>}
              <div ref={endRef}></div>
            </div>
          )}
        </section>
        <div className="composer-wrap">
          {attachments.length > 0 && (
            <div className="attachments">
              {attachments.map((item) => (
                <span className="attachment" key={item.id}>
                  📎 {item.name}
                  <button onClick={() => removeAttachment(item.id)} title="Remove">×</button>
                </span>
              ))}
            </div>
          )}
          <div className="composer">
            <input className="hidden-file" ref={fileRef} type="file" multiple accept="image/*,video/*,audio/*,.pdf,.txt,.md,.json,.csv,.log,.html,.css,.js,.jsx,.ts,.tsx,.py" onChange={(e) => addFiles(e.target.files)} />
            <button className="round" onClick={() => fileRef.current?.click()} title="Attach files">＋</button>
            <textarea ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKeyDown} placeholder="Ask Arka to inspect, test, or edit…" rows="1" />
            <button className={"round " + (listening ? "listening" : "")} disabled={!speechSupported} onClick={listening ? stopListen : startListen} title={speechSupported ? "Speak" : "Speech not supported"}>🎙️</button>
            <button className="round send" disabled={busy || (!input.trim() && attachments.length === 0)} onClick={() => askArka()} title="Send">➜</button>
          </div>
          <div className="fineprint">Arka can make mistakes. Review commands and outputs before applying production changes.</div>
        </div>
      </main>
    </div>
  );
}

class ArkaErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {error: null};
  }
  static getDerivedStateFromError(error) {
    return {error};
  }
  componentDidCatch(error) {
    window.__arkaUiErrors.push(error?.message || String(error));
  }
  render() {
    if (this.state.error) {
      return (
        <div className="app">
          <main className="main" style={{gridColumn: "1 / -1"}}>
            <div className="topbar"><strong>Arka</strong><div className="status"><span className="dot err"></span>UI recovered</div></div>
            <section className="chat has-messages">
              <div className="messages">
                <div className="msg arka">
                  <div className="avatar arka">A</div>
                  <div className="bubble">Arka hit a UI rendering error, but the page did not go blank. Refresh and try again. Error: {String(this.state.error.message || this.state.error)}</div>
                </div>
              </div>
            </section>
          </main>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById("root")).render(<ArkaErrorBoundary><App /></ArkaErrorBoundary>);
</script>
</body>
</html>
"""


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def extract_speak_text(raw: str) -> str:
    text = strip_ansi(raw)
    if "━━━ Answer ━━━" in text:
        text = text.split("━━━ Answer ━━━", 1)[1]
    text = " ".join(text.split())
    max_len = int(os.environ.get("AGENT_SPEAK_MAX", "450"))
    if len(text) > max_len:
        text = text[: max_len - 3].rstrip() + "..."
    return text


def _safe_upload_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name or "upload.bin").name).strip(".-")
    return cleaned[:120] or "upload.bin"


def save_media_upload(payload: dict) -> dict:
    """Save a base64 media upload and return non-secret metadata for agent prompts."""
    name = _safe_upload_name(str(payload.get("name") or "upload.bin"))
    media_type = str(payload.get("type") or "application/octet-stream")[:120]
    raw_data = str(payload.get("data") or "")
    if "," in raw_data and raw_data.split(",", 1)[0].startswith("data:"):
        raw_data = raw_data.split(",", 1)[1]
    try:
        data = base64.b64decode(raw_data, validate=True)
    except Exception as exc:
        raise ValueError("invalid base64 media payload") from exc
    if not data:
        raise ValueError("empty media upload")
    if len(data) > MAX_MEDIA_UPLOAD_BYTES:
        raise ValueError(f"media upload too large (max {MAX_MEDIA_UPLOAD_BYTES} bytes)")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    media_id = secrets.token_urlsafe(8)
    path = UPLOAD_DIR / f"{media_id}-{name}"
    path.write_bytes(data)
    return {
        "id": media_id,
        "name": name,
        "type": media_type,
        "bytes": len(data),
        "path": str(path),
    }


def parse_github_repo_url(text: str) -> RemoteRepo | None:
    match = _GITHUB_REPO_RE.search(text or "")
    if not match:
        return None
    owner = match.group(1).strip(".")
    repo = match.group(2).removesuffix(".git").strip(".")
    if not owner or not repo or owner.lower() in {"orgs", "repos"}:
        return None
    path = REMOTE_REPOS_DIR / owner / repo
    return RemoteRepo(owner=owner, repo=repo, url=f"https://github.com/{owner}/{repo}.git", path=path)


def wants_remote_repo_init(text: str) -> bool:
    """True when hosted input wants a GitHub repo to become the coding workspace."""
    if not parse_github_repo_url(text):
        return False
    clean = text or ""
    return bool(_GITHUB_INIT_RE.search(clean)) or bool(re.search(r"(?i)\bcode\s+init\b", clean))


def _gh_auth_help(repo: RemoteRepo) -> str:
    return (
        f"Could not access {repo.owner}/{repo.repo} from the hosted demo.\n\n"
        "If it is a private repo, configure GitHub auth for this Railway service:\n"
        "1. Create a fine-scoped GitHub token with read access to the repo.\n"
        "2. Set it as GH_TOKEN or GITHUB_TOKEN in Railway variables.\n"
        "3. Redeploy Arka.\n\n"
        "For local CLI use, run:\n"
        "  gh auth login\n"
        f"  arka code init https://github.com/{repo.owner}/{repo.repo}\n\n"
        "The hosted demo never starts an interactive gh auth login flow inside the browser."
    )


def ensure_remote_github_workspace(text: str) -> tuple[Path | None, str, int]:
    """Clone/fetch a GitHub repo URL into the hosted workspace cache and init code project."""
    repo = parse_github_repo_url(text)
    if repo is None:
        return None, "No GitHub repository URL found.", 2

    REMOTE_REPOS_DIR.mkdir(parents=True, exist_ok=True)
    repo.path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    token = env.get("GH_TOKEN") or env.get("GITHUB_TOKEN")
    clone_url = repo.url
    if token and clone_url.startswith("https://github.com/"):
        clone_url = "https://x-access-token:" + token + "@github.com/" + f"{repo.owner}/{repo.repo}.git"

    def _sanitize(raw: str) -> str:
        if token:
            raw = raw.replace(token, "<redacted>")
        return raw

    try:
        if (repo.path / ".git").is_dir():
            proc = subprocess.run(
                ["git", "-C", str(repo.path), "fetch", "--prune", "--depth", "1", "origin"],
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
            action = "updated"
        else:
            proc = subprocess.run(
                ["git", "clone", "--depth", "1", clone_url, str(repo.path)],
                capture_output=True,
                text=True,
                timeout=240,
                env=env,
            )
            action = "cloned"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"GitHub workspace setup failed: {exc}", 1

    if proc.returncode != 0:
        detail = _sanitize((proc.stderr or proc.stdout or "").strip())
        hint = _gh_auth_help(repo)
        if detail:
            hint += f"\n\nGit said:\n{detail}"
        return None, hint, int(proc.returncode or 1)

    try:
        from arka.core.code_project import init_project

        init_project(repo.path)
    except Exception as exc:
        return None, f"Repository was {action}, but code project init failed: {exc}", 1

    auth_note = "GitHub auth: token configured." if token else "GitHub auth: public clone/no token."
    msg = (
        f"Code workspace {action}: {repo.owner}/{repo.repo}\n"
        f"Root: {repo.path}\n"
        f"{auth_note}\n\n"
        "Next: ask Arka to inspect, test, review, or edit this repository."
    )
    return repo.path, msg, 0


def run_agent_remote(text: str) -> tuple[str, str, int]:
    """Run fish agent_hear without local TTS; return (full_output, speak_text, exit_code)."""
    text = text.strip()
    if not text:
        return "", "", 1

    env = os.environ.copy()
    env["AGENT_SPEAK"] = "0"

    cmd = f"agent_hear {shlex.quote(text)}"
    try:
        proc = subprocess.run(
            ["fish", "-ic", cmd],
            capture_output=True,
            text=True,
            env=env,
            timeout=int(os.environ.get("REMOTE_TIMEOUT", "600")),
        )
    except subprocess.TimeoutExpired:
        return "", "Sorry, that took too long.", 124

    output = (proc.stdout or "") + (proc.stderr or "")
    speak_text = extract_speak_text(output)
    return output.strip(), speak_text, proc.returncode


def _remote_profile() -> str:
    return (os.environ.get("ARKA_REMOTE_PROFILE") or os.environ.get("ARKA_HOSTED_PROFILE") or "").strip().lower()


def _coding_capabilities_text() -> str:
    skills = ", ".join(sorted(CODING_ALLOWED_SKILLS))
    return (
        "Arka Railway coding profile is active.\n"
        f"Allowed skill heads: {skills}\n"
        "Try: check repo health, run ci, review staged changes, route audit, inspect repo map.\n"
        "Hosted repo setup: paste a GitHub URL and say 'init this repo'. "
        "For private repos, set GH_TOKEN or GITHUB_TOKEN on Railway first."
    )


def _coding_greeting_text() -> str:
    return (
        "Hi — I’m Arka’s hosted coding demo. Upload a screenshot, video, log, or source file, "
        "paste a GitHub repo URL to initialize a workspace, or ask for a developer task like: "
        "check repo health, run ci, review staged changes, route audit, or inspect repo map."
    )


def run_coding_remote(text: str) -> tuple[str, str, int]:
    """Run a hosted-safe Python route/dispatch path for coding/devtool skills."""
    text = text.strip()
    if not text:
        return "", "", 1
    if text.lower() in {"hi", "hello", "hey", "yo", "namaste"}:
        msg = _coding_greeting_text()
        return msg, msg, 0
    if text.lower() in {"capabilities", "skills", "help", "status"}:
        return _coding_capabilities_text(), _coding_capabilities_text(), 0
    if wants_remote_repo_init(text):
        _root, msg, code = ensure_remote_github_workspace(text)
        return msg, extract_speak_text(msg), code

    try:
        from arka.dispatch import run_skill
        from arka.router import route
        from arka.core.code_project import apply_env
    except ImportError as exc:
        return f"Arka coding runtime unavailable: {exc}", "", 1

    root = apply_env()
    decision = route(text)
    skill_line = decision.skill if decision else text
    head = skill_line.split(None, 1)[0].strip().lower() if skill_line.strip() else ""
    head = head.replace("-", "_")
    if head not in CODING_ALLOWED_SKILLS:
        msg = (
            f"Blocked in Railway coding profile: {head or text!r} is not a coding/devtool skill.\n"
            + _coding_capabilities_text()
        )
        return msg, msg, 2

    buf = io.StringIO()
    os.environ.setdefault("ARKA_HOSTED_MODE", "1")
    os.environ.setdefault("ARKA_MCP_ENABLE_PERSONAL_SKILLS", "0")
    os.environ["ARKA_CAPTURE_STDIO"] = "1"
    old_cwd = Path.cwd()
    try:
        if root is not None:
            os.chdir(root)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = run_skill(skill_line)
    except SystemExit as exc:
        code = int(exc.code) if isinstance(exc.code, int) else 2
    except Exception as exc:
        return f"Arka coding skill failed: {exc}", "", 1
    finally:
        os.chdir(old_cwd)
        os.environ.pop("ARKA_CAPTURE_STDIO", None)
    output = strip_ansi(buf.getvalue()).strip() or f"Skill completed: {skill_line}"
    return output, extract_speak_text(output), int(code or 0)


def transcribe_wav(wav_bytes: bytes) -> str:
    """Optional server-side STT when phone sends audio instead of text."""
    venv_py = Path.home() / ".config" / "fish" / "venv-arka" / "bin" / "python3"
    tmp = CACHE / "upload.wav"
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(wav_bytes)
    code = f"""
import json, sys, wave
from pathlib import Path
from vosk import KaldiRecognizer, Model
wav_path = Path({str(tmp)!r})
model_dir = Path.home() / ".cache" / "vosk-model-small-en-us"
model = Model(str(model_dir))
with wave.open(str(wav_path), "rb") as wf:
    rec = KaldiRecognizer(model, wf.getframerate())
    rec.SetWords(False)
    while True:
        data = wf.readframes(4000)
        if not data:
            break
        rec.AcceptWaveform(data)
    print(json.loads(rec.FinalResult()).get("text", ""))
"""
    py = str(venv_py if venv_py.exists() else sys.executable)
    proc = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "transcription failed")
    return proc.stdout.strip()


class ArkaRemoteHandler(BaseHTTPRequestHandler):
    server_version = "ArkaRemote/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[arka-remote] {self.address_string()} - {fmt % args}", flush=True)

    def _check_auth(self) -> bool:
        from arka.env import env_get

        token = env_get("REMOTE_TOKEN")
        if not token:
            return False
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip() == token
        return self.headers.get("X-Arka-Token", "").strip() == token

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else b""

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/app", "/mobile"):
            body = MOBILE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/v1/health":
            self._json(
                200,
                {
                    "ok": True,
                    "agent": os.environ.get("AGENT_NAME", "arka"),
                    "speak_lang": os.environ.get("SPEAK_LANG", "en-IN"),
                },
            )
            return
        if path == "/v1/handoff":
            sys.path.insert(0, str(Path.home() / ".config" / "fish"))
            from arka.agent.core import handoff_api_list

            items = handoff_api_list()
            self._json(200, {"ok": True, "items": items[-20:]})
            return
        if path == "/v1/notifications":
            sys.path.insert(0, str(Path.home() / ".config" / "fish"))
            from arka.agent.talents import handoff_notifications_list

            unread = urlparse(self.path).query.find("unread=1") >= 0
            items = handoff_notifications_list(unread_only=unread)
            self._json(200, {"ok": True, "items": items[-10:]})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if not self._check_auth():
            self._json(401, {"ok": False, "error": "unauthorized — check REMOTE_TOKEN in .env"})
            return

        path = urlparse(self.path).path

        if path == "/v1/agent":
            try:
                data = json.loads(self._read_body().decode("utf-8"))
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON"})
                return

            text = (data.get("text") or "").strip()
            if not text:
                self._json(400, {"ok": False, "error": "missing text"})
                return

            if _remote_profile() == "coding":
                output, speak_text, code = run_coding_remote(text)
            else:
                output, speak_text, code = run_agent_remote(text)
            remote_speak = data.get("remote_speak", True)
            self._json(
                200,
                {
                    "ok": code == 0,
                    "exit_code": code,
                    "profile": _remote_profile() or "default",
                    "output": output,
                    "speak_text": speak_text if remote_speak else "",
                },
            )
            return

        if path == "/v1/media":
            if int(self.headers.get("Content-Length", "0")) > MAX_MEDIA_UPLOAD_BYTES * 2:
                self._json(413, {"ok": False, "error": f"media upload too large (max {MAX_MEDIA_UPLOAD_BYTES} bytes)"})
                return
            try:
                data = json.loads(self._read_body().decode("utf-8"))
                media = save_media_upload(data)
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON"})
                return
            except ValueError as exc:
                self._json(400 if "large" not in str(exc) else 413, {"ok": False, "error": str(exc)})
                return
            self._json(200, {"ok": True, "media": media})
            return

        if path == "/v1/transcribe":
            ct = self.headers.get("Content-Type", "")
            body = self._read_body()
            if len(body) > 10 * 1024 * 1024:
                self._json(413, {"ok": False, "error": "audio too large (max 10MB)"})
                return
            try:
                if "json" in ct:
                    payload = json.loads(body.decode("utf-8"))
                    import base64

                    audio = base64.b64decode(payload.get("audio", ""))
                else:
                    audio = body
                text = transcribe_wav(audio)
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
                return
            self._json(200, {"ok": True, "text": text})
            return

        if path == "/v1/handoff":
            try:
                data = json.loads(self._read_body().decode("utf-8"))
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON"})
                return
            sys.path.insert(0, str(Path.home() / ".config" / "fish"))
            from arka.agent.core import handoff_api_add, handoff_api_list

            action = (data.get("action") or "add").strip().lower()
            if action == "list":
                items = handoff_api_list(data.get("status"))
                self._json(200, {"ok": True, "items": items})
                return
            text = (data.get("text") or "").strip()
            if not text:
                self._json(400, {"ok": False, "error": "missing text"})
                return
            item = handoff_api_add(text, source=data.get("source") or "phone")
            self._json(200, {"ok": True, "item": item})
            return

        if path == "/v1/notifications/read":
            try:
                data = json.loads(self._read_body().decode("utf-8")) if self.headers.get("Content-Length") else {}
            except json.JSONDecodeError:
                data = {}
            sys.path.insert(0, str(Path.home() / ".config" / "fish"))
            from arka.agent.talents import handoff_notifications_mark_read

            handoff_notifications_mark_read(data.get("id") or None)
            self._json(200, {"ok": True})
            return

        if path == "/v1/inbox":
            try:
                data = json.loads(self._read_body().decode("utf-8"))
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON"})
                return
            from_num = (data.get("from") or data.get("phone") or "").strip()
            text = (data.get("text") or data.get("message") or "").strip()
            source = (data.get("source") or "whatsapp").strip()
            if not from_num or not text:
                self._json(400, {"ok": False, "error": "missing from or text"})
                return
            sys.path.insert(0, str(Path.home() / ".config" / "fish"))
            from arka.integrations.whatsapp_inbox import handle_inbox_message

            result = handle_inbox_message(from_num, text, source=source)
            code = 200 if result.get("ok") else 403
            self._json(code, result)
            return

        self._json(404, {"ok": False, "error": "not found"})


def ensure_token() -> str:
    _bootstrap_env()
    from arka.env import env_get
    from arka.paths import env_file

    token = env_get("REMOTE_TOKEN")
    if token:
        os.environ["REMOTE_TOKEN"] = token
        return token

    token = secrets.token_urlsafe(24)
    line = f"REMOTE_TOKEN={token}\n"
    target = env_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        content = target.read_text(encoding="utf-8", errors="replace")
        if "REMOTE_TOKEN=" not in content:
            with target.open("a", encoding="utf-8") as fh:
                fh.write(line)
    else:
        target.write_text(line, encoding="utf-8")
    os.environ["REMOTE_TOKEN"] = token
    print(f"[arka-remote] Generated REMOTE_TOKEN and saved to {target}", flush=True)
    return token


def local_ip() -> str:
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def write_pid() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()))


def remove_pid() -> None:
    PID_PATH.unlink(missing_ok=True)


def serve() -> int:
    _bootstrap_env()
    from arka.env import env_get

    host = env_get("REMOTE_HOST") or "0.0.0.0"
    port = int(os.environ.get("PORT") or env_get("REMOTE_PORT") or "8765")
    if _remote_profile() == "coding":
        os.environ.setdefault("ARKA_HOSTED_MODE", "1")
        os.environ.setdefault("ARKA_MODEL_MODE", "auto")
        os.environ.setdefault("ARKA_MCP_ENABLE_PERSONAL_SKILLS", "0")
    token = ensure_token()

    write_pid()

    def _stop(_signum, _frame):
        print("[arka-remote] Stopping", flush=True)
        remove_pid()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    httpd = ThreadingHTTPServer((host, port), ArkaRemoteHandler)
    ip = local_ip()
    print(f"[arka-remote] Listening on http://{ip}:{port}/", flush=True)
    print(f"[arka-remote] Mobile UI: http://{ip}:{port}/", flush=True)
    print(f"[arka-remote] Token: {token}", flush=True)
    print("[arka-remote] Phone does STT/TTS · PC runs agent", flush=True)

    try:
        httpd.serve_forever()
    finally:
        remove_pid()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Arka remote server")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve")
    sub.add_parser("stop")
    args = parser.parse_args()

    if args.cmd == "serve":
        return serve()
    if args.cmd == "stop":
        if not PID_PATH.exists():
            return 0
        pid = int(PID_PATH.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        PID_PATH.unlink(missing_ok=True)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
