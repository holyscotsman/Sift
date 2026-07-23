// Ask — grounded natural-language Q&A over the snapshot. Answers cite the library
// movies they were grounded on (source chips). Retrieval is deterministic; the LLM
// only phrases the answer. Streaming is a later polish — this posts and renders.

import { useEffect, useRef, useState } from "react";

import { SparkleIcon } from "@/components/icons";
import { api } from "@/lib/api";
import { useDrawer } from "@/lib/drawer";
import { formatAnswer } from "@/lib/format";
import type { AskAlternate, AskResponse, AskSource, ProfileResponse } from "@/lib/types";

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
  alternate: AskAlternate | null;
}
type Msg = UserMsg | AssistantMsg;

const STATIC_SUGGESTIONS = [
  "What sci-fi movies do I have from the 90s?",
  "Which Christopher Nolan films are in my library?",
  "Do I have any low-rated action movies?",
];

// Chips grounded in what the user actually owns — top genre/director/era from the
// taste profile. An empty profile (pre-scan) falls back to the static examples.
function buildSuggestions(p: ProfileResponse): string[] {
  const out: string[] = [];
  const genre = p.genres[0]?.name;
  const director = p.directors[0]?.name;
  // Eras arrive chronologically sorted — take the biggest bucket, not the earliest.
  const era = [...p.eras].sort((a, b) => b.count - a.count)[0]?.name;
  if (genre) out.push(`What are my highest-rated ${genre.toLowerCase()} movies?`);
  if (director) out.push(`Which ${director} films do I have?`);
  if (era) out.push(`What do I have from the ${era}?`);
  return out.length ? out : STATIC_SUGGESTIONS;
}

export function Ask() {
  const [thread, setThread] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>(STATIC_SUGGESTIONS);
  // Side-by-side answers from both providers — offered only when the server
  // says tandem is fully configured.
  const [compareAvailable, setCompareAvailable] = useState(false);
  const [compare, setCompare] = useState(false);
  const { open: openDrawer } = useDrawer();
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getProfile()
      .then((p) => {
        if (!cancelled) setSuggestions(buildSuggestions(p));
      })
      .catch(() => undefined);
    api
      .getSettings()
      .then((s) => {
        if (!cancelled) setCompareAvailable(s.ai_compare_available);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [thread, thinking]);

  async function send(q: string) {
    const query = q.trim();
    if (!query || thinking) return;
    setInput("");
    setThread((t) => [...t, { role: "user", text: query }]);
    setThinking(true);
    try {
      const res: AskResponse = await api.ask(query, compare ? "compare" : "single");
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
          alternate: res.alternate,
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
          alternate: null,
        },
      ]);
    } finally {
      setThinking(false);
      // Follow-ups shouldn't need a click — the conversation stays in the keyboard.
      inputRef.current?.focus();
    }
  }

  return (
    <div className="page-enter flex h-[calc(100vh-190px)] flex-col">
      <div className="mb-3 flex items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">Ask</h1>
          <p className="mt-1 text-sm text-fg2">
            Natural-language questions grounded in your library — answers cite the titles they used.
          </p>
        </div>
        {thread.length > 0 && (
          <button
            onClick={() => {
              setThread([]);
              setInput("");
              inputRef.current?.focus();
            }}
            className="shrink-0 rounded-pill border border-line px-3 py-1.5 text-xs font-semibold text-fg2 hover:bg-bg2"
          >
            New conversation
          </button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        {thread.length === 0 && (
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <SparkleIcon size={28} className="text-accent" />
            <p className="text-sm text-fg2">Ask anything about your library.</p>
            <div className="flex flex-wrap justify-center gap-2">
              {suggestions.map((s) => (
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
              <div key={i} className={m.alternate ? "w-full" : "max-w-[85%]"}>
                <div className={m.alternate ? "grid grid-cols-1 gap-3 md:grid-cols-2" : ""}>
                  <div>
                    <div className="panel px-4 py-3">
                      {m.alternate && (
                        <p className="eyebrow mb-2">{m.model || m.provider}</p>
                      )}
                      <div className="space-y-2 text-sm text-fg">{formatAnswer(m.answer)}</div>
                    </div>
                    <p className="mt-1 px-1 text-[11px] text-fg3">
                      {m.provider === "stub"
                        ? "grounded answer — connect a model in Settings › Connections for richer phrasing"
                        : `${m.model}`}
                      {m.latency ? ` · ${Math.round(m.latency)}ms` : ""}
                    </p>
                  </div>
                  {m.alternate && (
                    <div>
                      <div className="panel px-4 py-3">
                        <p className="eyebrow mb-2">{m.alternate.model || m.alternate.provider}</p>
                        <div className="space-y-2 text-sm text-fg">
                          {formatAnswer(m.alternate.answer)}
                        </div>
                      </div>
                      <p className="mt-1 px-1 text-[11px] text-fg3">
                        {m.alternate.model} · {Math.round(m.alternate.latency_ms)}ms
                      </p>
                    </div>
                  )}
                </div>
                {m.sources.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
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
        {compareAvailable && (
          <button
            type="button"
            onClick={() => setCompare((c) => !c)}
            aria-pressed={compare}
            title="Ask both models and compare their answers side by side"
            className={`shrink-0 rounded-pill border px-3 py-2 text-xs font-semibold ${
              compare
                ? "border-accent-line bg-accent-soft text-accent"
                : "border-line text-fg2 hover:bg-bg2"
            }`}
          >
            Compare
          </button>
        )}
        <input
          ref={inputRef}
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
