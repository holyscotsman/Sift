// Which Plex libraries Sift reads, and whether each is films or television.
//
// Worth showing rather than assuming. Plex calls a Home Videos library a *movie*
// library, so left to itself Sift reads family footage as films — into the
// removal queue, the film counts, and the size baselines every verdict is
// measured against. Sift leaves those alone by default because they carry no
// metadata agent, but you should be able to see that decision and overrule it.

import { useEffect, useState } from "react";

import { useToast } from "@/components/Toast";
import { Pill, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { SectionPlan } from "@/lib/types";

const KINDS = [
  { value: "movie", label: "Films" },
  { value: "show", label: "TV" },
  { value: "ignore", label: "Ignore" },
] as const;

function tone(kind: string): "keep" | "accent" | "neutral" {
  if (kind === "movie") return "keep";
  if (kind === "show") return "accent";
  return "neutral";
}

export function SectionsForm() {
  const [sections, setSections] = useState<SectionPlan[] | null>(null);
  const [detail, setDetail] = useState("");
  const [pending, setPending] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const toastError = useToast();

  useEffect(() => {
    let live = true;
    api
      .sections()
      .then((r) => {
        if (!live) return;
        setSections(r.sections);
        setDetail(r.detail);
      })
      .catch(() => live && setDetail("Couldn't read your Plex libraries."));
    return () => {
      live = false;
    };
  }, []);

  const dirty = Object.keys(pending).length > 0;

  async function save() {
    if (!sections) return;
    setSaving(true);
    try {
      // Send the whole map, not just what changed: an override that has been
      // set back to Plex's own answer still has to be recorded, or the old one
      // sticks.
      const merged: Record<string, string> = {};
      for (const section of sections) {
        const value = pending[section.title] ?? (section.overridden ? section.kind : null);
        if (value) merged[section.title] = value;
      }
      const result = await api.saveSections(merged);
      setSections(result.sections);
      setPending({});
    } catch (e) {
      toastError((e as { message?: string })?.message || "Couldn't save that.");
    } finally {
      setSaving(false);
    }
  }

  if (!sections) {
    return detail ? (
      <p className="text-sm text-fg2">{detail}</p>
    ) : (
      <div className="flex flex-col gap-2" aria-busy="true">
        <Skeleton className="h-10" />
        <Skeleton className="h-10" />
      </div>
    );
  }

  if (sections.length === 0) {
    return <p className="text-sm text-fg2">{detail || "No Plex libraries found."}</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="max-w-prose text-sm text-fg2">
        Every show library counts as TV — Cartoons, Anime, Game Shows and the rest — so there is
        nothing to set up for those. What does need a look is anything Plex files as a film library
        that isn&rsquo;t one: home video collections carry no metadata agent, so Sift skips them by
        default rather than reading holiday footage as a film collection.
      </p>

      <div className="panel divide-y divide-line">
        {sections.map((section) => {
          const current = pending[section.title] ?? section.kind;
          return (
            <div key={section.key} className="flex flex-wrap items-center gap-3 p-3.5">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-semibold">{section.title}</span>
                  <Pill tone={tone(current)}>
                    {KINDS.find((k) => k.value === current)?.label ?? current}
                  </Pill>
                </div>
                <p className="mt-0.5 text-xs text-fg3">
                  Plex calls it a {section.plex_type} library · {section.reason}
                </p>
              </div>
              <div className="flex shrink-0 gap-1" role="group" aria-label={section.title}>
                {KINDS.map((kind) => (
                  <button
                    key={kind.value}
                    onClick={() =>
                      setPending((p) => ({ ...p, [section.title]: kind.value }))
                    }
                    aria-pressed={current === kind.value}
                    className={`rounded-md border px-2.5 py-1 text-xs font-semibold ${
                      current === kind.value
                        ? "border-accent bg-accent-soft text-accent"
                        : "border-line text-fg2 hover:bg-bg2"
                    }`}
                  >
                    {kind.label}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={() => void save()}
          disabled={!dirty || saving}
          className="rounded-md border border-line px-4 py-2 text-sm font-semibold text-fg2 hover:bg-bg2 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save libraries"}
        </button>
        {dirty ? (
          <span className="text-xs text-fg2">Takes effect on the next scan.</span>
        ) : null}
      </div>
    </div>
  );
}
