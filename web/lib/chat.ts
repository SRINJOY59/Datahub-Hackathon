// SSE over a POST body. Browser EventSource can't carry a request body, so
// this parses the same wire format by hand from a fetch() ReadableStream —
// the standard pattern for streaming chat over plain HTTP without a
// websocket dependency.

import { API_URL } from "./graphql";

export type ChatEvent =
  | { type: "session"; sessionId: string }
  | { type: "thinking"; text: string }
  | { type: "delta"; text: string }
  | { type: "error"; message: string }
  | { type: "done" };

function unescape(data: string): string {
  // Mirrors api/chat_routes.py's _sse(): backslash-escaped so a multi-line
  // answer survives SSE's one-event-per-blank-line-terminated-frame format.
  return data.replace(/\\n/g, "\n").replace(/\\\\/g, "\\");
}

export async function* streamChat(
  message: string,
  sessionId: string | null,
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal,
  });

  if (!res.ok || !res.body) {
    yield { type: "error", message: `Chat request failed: HTTP ${res.status}` };
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data = line.slice(6);
      }
      const text = unescape(data);

      if (event === "session") yield { type: "session", sessionId: text };
      else if (event === "thinking") yield { type: "thinking", text };
      else if (event === "delta") yield { type: "delta", text };
      else if (event === "error") yield { type: "error", message: text };
      else if (event === "done") yield { type: "done" };
    }
  }
}

export interface ChatSession {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  createdAt: string;
}

export async function fetchSessions(): Promise<ChatSession[]> {
  const res = await fetch(`${API_URL}/chat/sessions`);
  const data = await res.json();
  return (data.sessions ?? []).map((s: {
    id: string; title: string; created_at: string; updated_at: string;
  }) => ({
    id: s.id, title: s.title, createdAt: s.created_at, updatedAt: s.updated_at,
  }));
}

export async function fetchSessionHistory(sessionId: string): Promise<ChatMessage[]> {
  const res = await fetch(`${API_URL}/chat/sessions/${sessionId}`);
  const data = await res.json();
  return (data.messages ?? []).map((m: {
    role: "user" | "assistant"; content: string; created_at: string;
  }) => ({ role: m.role, content: m.content, createdAt: m.created_at }));
}
