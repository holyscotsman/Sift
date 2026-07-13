// On-brand placeholders for screens whose backend (analysis / AI) arrives in
// Phase 1–2. They keep the shell navigable and describe what's coming.

import { PlaceholderPage } from "@/components/ui";

export const Missing = () => (
  <PlaceholderPage
    title="Missing"
    note="Collection gaps (deterministic) and taste-based recommendations (AI, ranked by fit) land with the Phase 1–2 analysis engine. This screen will show owned vs missing collection slots and a ranked recommendation list with rationale."
  />
);

export const Junk = () => (
  <PlaceholderPage
    title="Junk — removal queue"
    note="Sift never deletes on its own. This queue will list vote-weighted junk candidates with per-signal breakdowns and an approval-gated, irreversible-delete confirm modal. Wired once the Phase-1 junk scorer and the action-execution path are live."
  />
);

export const Ask = () => (
  <PlaceholderPage
    title="Ask"
    note="Grounded natural-language Q&A over the snapshot, with Local / Anthropic / Compare modes and streamed answers. Arrives with the Phase-2 provider layer."
  />
);

export const TasteProfile = () => (
  <PlaceholderPage
    title="Taste Profile"
    note="Editable weight sliders over genres, directors, cast, keywords, and eras, with a live recompute. Built on the Phase-2 profile embedding."
  />
);

export const Settings = () => (
  <PlaceholderPage
    title="Settings"
    note="Connections, model routing, scoring thresholds (with live 'would affect N titles' preview), the autonomy tiers (Delete = approval-required, locked), and appearance. The read-only connection health is already live in the header; editable settings land with the settings API."
  />
);
