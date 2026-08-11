const TOKEN_KEY = "arka.apiToken";
const CHAT_ID_KEY = "arka.chatId";
export const SESSION_CHANNEL = "web";

export function getChatId(): string {
  let id = localStorage.getItem(CHAT_ID_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(CHAT_ID_KEY, id);
  }
  return id;
}

export function resetChatId(): string {
  const id = crypto.randomUUID();
  localStorage.setItem(CHAT_ID_KEY, id);
  return id;
}

export function getApiToken(): string {
  return localStorage.getItem(TOKEN_KEY) || import.meta.env.VITE_ARKA_TOKEN || "";
}

export function setApiToken(token: string): void {
  if (token.trim()) {
    localStorage.setItem(TOKEN_KEY, token.trim());
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export type HealthResponse = {
  ok: boolean;
  agent?: string;
  speak_lang?: string;
  error?: string;
};

export type RouteInfo = {
  ok: boolean;
  skill: string;
  source?: string;
  kind?: string;
  rule?: string;
  decision?: string;
};

export type AgentResponse = {
  ok: boolean;
  exit_code?: number;
  profile?: string;
  output?: string;
  speak_text?: string;
  route?: RouteInfo;
  error?: string;
};

export type CapabilitiesResponse = {
  ok: boolean;
  dispatch_skills: string[];
  count: number;
  source?: string;
  error?: string;
};

export type DoctorResponse = {
  ok: boolean;
  output?: string;
  exit_code?: number;
  error?: string;
};

export type SessionTurn = {
  role: "user" | "assistant" | "system" | string;
  text: string;
  when?: string;
  ts?: number;
};

export type SessionResumeResponse = {
  ok: boolean;
  key?: string;
  channel?: string;
  chat_id?: string;
  title?: string;
  turns?: SessionTurn[];
  turn_count?: number;
  error?: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  const token = getApiToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(path, { ...init, headers });
  const data = (await response.json()) as T & { error?: string };
  if (!response.ok && !("ok" in data)) {
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  return data;
}

export type DesktopConfig = {
  ok: boolean;
  app?: string;
  has_token?: boolean;
  remote_url?: string;
  bridge_port?: number;
  error?: string;
};

export function fetchDesktopConfig(): Promise<DesktopConfig> {
  return request<DesktopConfig>("/v1/config");
}

export function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/v1/health");
}

export function fetchCapabilities(): Promise<CapabilitiesResponse> {
  return request<CapabilitiesResponse>("/v1/capabilities");
}

export function fetchDoctor(): Promise<DoctorResponse> {
  return request<DoctorResponse>("/v1/doctor");
}

export function previewRoute(text: string): Promise<RouteInfo> {
  return request<RouteInfo>("/v1/route", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

export function fetchSessionHistory(limit = 100): Promise<SessionResumeResponse> {
  const chatId = getChatId();
  const params = new URLSearchParams({
    channel: SESSION_CHANNEL,
    chat_id: chatId,
    limit: String(limit),
  });
  return request<SessionResumeResponse>(`/v1/sessions/resume?${params.toString()}`);
}

export function resetSessionHistory(): Promise<{ ok: boolean; error?: string }> {
  return request<{ ok: boolean; error?: string }>("/v1/sessions/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ channel: SESSION_CHANNEL, chat_id: getChatId() }),
  });
}

export function askAgent(text: string): Promise<AgentResponse> {
  return request<AgentResponse>("/v1/agent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      remote_speak: false,
      channel: SESSION_CHANNEL,
      chat_id: getChatId(),
    }),
  });
}
