// Ask — grounded natural-language Q&A over the snapshot. Answers cite the library
// movies they were grounded on (source chips). Retrieval is deterministic; the LLM
// only phrases the answer. Streaming is a later polish — this posts and renders.

import { useEffect, useRef, useState } from "react";

import { SparkleIcon } from "@/components/icons";
import { api } from "@/lib/api";
import { useDrawer } from "@/lib/drawer";
import type { AskResponse, AskSource } from "@/lib/types";

interface UserMsg {
  role: "user";
  text: string;
}
interface AssistantMsg {
  role: "assistant";
  answer: string;
  provider: string;
  model: string;
  latency: number;
  aiConfigured: boolean;
  sources: AskSource[];
}
type Msg = UserMsg | AssistantMsg;

const SUGGESTIONS = [
  "What sci-fi movies do I have from the 90s?",
  "Which Christopher Nolan films are in my library?",
  "Do I have any low-rated action movies?",
];

export function Ask() {
  const [thread, setThread] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const { open: openDrawer } = useDrawer();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [thread, thinking]);

  async function send(q: string) {
    const query = q.trim();
    if (!query || thinking) return;
    setInput("");
    setThread((t) => [...t, { role: "user", text: query }]);
    setThinking(true);
    try {
      const res: AskResponse = await api.ask(query);
      setThread((t) => [
        ...t,
        {
          role: "assistant",
          answer: res.answer,
          provider: res.provider,
          model: res.model,
          latency: res.latency_ms,
          aiConfigured: res.ai_configured,
          sources: res.sources,
        },
      ]);
    } catch {
      setThread((t) => [
        ...t,
        {
          role: "assistant",
          answer: "Sorry — I couldn't reach the server for that.",
          provider: "error",
          model: "",
          latency: 0,
          aiConfigured: false,
          sources: [],
        },
      ]);
    } finally {
      setThinking(false);
    }
  }

  return (
    <div className="page-enter flex h-[calc(100vh-190px)] flex-col">
      <div className="mb-3">
        <h1 className="font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">Ask</h1>
        <p className="mt-1 text-sm text-fg2">
          Natural-language questions grounded in your library — answers cite the titles they used.
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        {thread.length === 0 && (
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <SparkleIcon size={28} className="text-accent" />
            <p className="text-sm text-fg2">Ask anything about your library.</p>
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-pill border border-line px-3 py-1.5 text-sm text-fg2 hover:bg-bg2"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex flex-col gap-4">
          {thread.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[80%] rounded-lg rounded-br-sm bg-accent-soft px-3.5 py-2 text-sm text-fg">
                  {m.text}
                </div>
              </div>
            ) : (
              <div key={i} className="max-w-[85%]">
                <div className="panel px-4 py-3">
                  <p className="whitespace-pre-wrap text-sm text-fg">{m.answer}</p>
                  {m.sources.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {m.sources.map((s) => (
                        <button
                          key={s.tmdb_id}
                          onClick={() => openDrawer(s.tmdb_id)}
                          className="rounded-pill bg-bg2 px-2 py-0.5 text-[11px] text-fg2 hover:text-fg"
                        >
                          {s.title}
                          {s.year ? ` · ${s.year}` : ""}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <p className="mt-1 px-1 text-[11px] text-fg3">
                  {m.provider === "stub" ? "no model — add ANTHROPIC_API_KEY" : `${m.model}`}
                  {m.latency ? ` · ${Math.round(m.latency)}ms` : ""}
                </p>
              </div>
            ),
          )}
          {thinking && (
            <div className="max-w-[85%]">
              <div className="panel px-4 py-3 text-sm text-fg3">
                <span className="inline-flex items-center gap-1">
                  Thinking
                  <span style={{ animation: "sift-pulse 1s infinite" }}>…</span>
                </span>
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
        className="mt-3 flex items-center gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about your library…"
          className="flex-1 rounded-pill border border-line bg-panel px-4 py-2.5 text-sm text-fg placeholder:text-fg3 focus:outline-none"
        />
        <button
          type="submit"
          disabled={!input.trim() || thinking}
          className="gradient-fill rounded-pill px-5 py-2.5 text-sm font-bold shadow-glow disabled:opacity-60"
        >
          Send
        </button>
      </form>
    </div>
  );
}
