// On-brand placeholders for screens whose backend (analysis / AI) arrives in
// Phase 1–2. They keep the shell navigable and describe what's coming.

import { PlaceholderPage } from "@/components/ui";

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
