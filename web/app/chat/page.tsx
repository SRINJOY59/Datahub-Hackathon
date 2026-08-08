"use client";

import { useEffect, useRef, useState } from "react";
import { streamChat, fetchSessions, fetchSessionHistory, type ChatSession } from "@/lib/chat";
import CitedText from "@/components/CitedText";

interface Message {
  role: "user" | "assistant";
  content: string;
}

const STORAGE_KEY = "sentinel-chat-session";

export default function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [thinking, setThinking] = useState("");
  const [live, setLive] = useState("");
  const [showThinking, setShowThinking] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const refreshSessions = () => fetchSessions().then(setSessions).catch(() => {});

  useEffect(() => {
    const stored = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
    if (stored) {
      setSessionId(stored);
      fetchSessionHistory(stored)
        .then((hist) => setMessages(hist.map((m) => ({ role: m.role, content: m.content }))))
        .catch(() => {});
    }
    refreshSessions();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, live, thinking]);

  async function send() {
    const question = input.trim();
    if (!question || streaming) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: question }]);
    setStreaming(true);
    setThinking("");
    setLive("");

    const controller = new AbortController();
    abortRef.current = controller;
    let finalAnswer = "";
    let finalThinking = "";

    try {
      for await (const evt of streamChat(question, sessionId, controller.signal)) {
        if (evt.type === "session") {
          setSessionId(evt.sessionId);
          localStorage.setItem(STORAGE_KEY, evt.sessionId);
        } else if (evt.type === "thinking") {
          finalThinking += evt.text;
          setThinking(finalThinking);
        } else if (evt.type === "delta") {
          finalAnswer += evt.text;
          setLive(finalAnswer);
        } else if (evt.type === "error") {
          finalAnswer += `\n\n[error: ${evt.message}]`;
          setLive(finalAnswer);
        }
      }
    } finally {
      if (finalAnswer.trim()) {
        setMessages((m) => [...m, { role: "assistant", content: finalAnswer.trim() }]);
      }
      setLive("");
      setThinking("");
      setStreaming(false);
      refreshSessions();
    }
  }

  function newSession() {
    setSessionId(null);
    setMessages([]);
    localStorage.removeItem(STORAGE_KEY);
  }

  function openSession(id: string) {
    setSessionId(id);
    localStorage.setItem(STORAGE_KEY, id);
    fetchSessionHistory(id)
      .then((hist) => setMessages(hist.map((m) => ({ role: m.role, content: m.content }))))
      .catch(() => {});
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-57px)] max-w-7xl">
      <aside className="hidden w-64 shrink-0 border-r border-border p-4 md:block">
        <button
          onClick={newSession}
          className="w-full rounded-lg border border-border px-3 py-2 text-sm hover:bg-surface-raised"
        >
          + New conversation
        </button>
        <div className="mt-4 space-y-1 overflow-y-auto scrollbar-thin">
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => openSession(s.id)}
              className={`block w-full truncate rounded-md px-2 py-1.5 text-left text-xs ${
                s.id === sessionId
                  ? "bg-accent-soft text-accent"
                  : "text-muted hover:bg-surface-raised hover:text-foreground"
              }`}
            >
              {s.title || "New conversation"}
            </button>
          ))}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="border-b border-border px-6 py-4">
          <h1 className="text-lg font-semibold">Ask the on-call</h1>
          <p className="text-xs text-muted">
            Grounded in the incident store — cites INC-ids for anything it references.
          </p>
        </div>

        <div className="flex-1 overflow-y-auto scrollbar-thin px-6 py-6">
          {messages.length === 0 && !streaming && (
            <div className="mx-auto max-w-md pt-16 text-center text-sm text-muted">
              Ask things like &quot;what happened to stg_transactions?&quot; or
              &quot;how many incidents this week, and what did they cost?&quot;
            </div>
          )}

          <div className="mx-auto max-w-3xl space-y-5">
            {messages.map((m, i) => (
              <Bubble key={i} role={m.role} content={m.content} />
            ))}

            {streaming && (
              <div className="space-y-2">
                {thinking && (
                  <div>
                    <button
                      onClick={() => setShowThinking((v) => !v)}
                      className="text-xs text-muted hover:text-foreground"
                    >
                      {showThinking ? "▾" : "▸"} thinking…
                    </button>
                    {showThinking && (
                      <p className="mt-1 max-h-32 overflow-y-auto rounded-md bg-surface p-2 text-xs italic text-muted">
                        {thinking}
                      </p>
                    )}
                  </div>
                )}
                {live ? (
                  <Bubble role="assistant" content={live} />
                ) : (
                  <div className="flex items-center gap-1.5 text-xs text-muted">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                    answering…
                  </div>
                )}
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="border-t border-border p-4">
          <div className="mx-auto flex max-w-3xl items-center gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send())}
              placeholder="Ask about an incident, asset, or trend…"
              className="flex-1 rounded-lg border border-border bg-surface px-4 py-2.5 text-sm outline-none focus:border-accent"
              disabled={streaming}
            />
            <button
              onClick={send}
              disabled={streaming || !input.trim()}
              className="rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white disabled:opacity-40"
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Bubble({ role, content }: { role: "user" | "assistant"; content: string }) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser ? "bg-accent text-white whitespace-pre-wrap shadow-md shadow-accent/10" : "card border border-border bg-surface/90 shadow-sm"
        }`}
      >
        {isUser ? content : <CitedText text={content} />}
      </div>
    </div>
  );
}
