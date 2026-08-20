// The form the original report was about: "why are my keys not being saved?"
//
// That turned out to be a server-side decryption problem, not this component —
// but this component was at 38% coverage and is the only thing standing between
// a typed key and the database, so "it wasn't this" was a guess rather than a
// fact. It is a fact now.
//
// The behaviour worth guarding hardest is the *blank* field. Blank means "keep
// what is stored", because a saved secret comes back masked and there is nothing
// to re-type. Get that backwards and saving one field wipes every other key on
// the screen — which is indistinguishable, from the outside, from keys that were
// never saved at all.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectionsForm } from "@/components/ConnectionsForm";
import type { ServiceSpec } from "@/components/ConnectionsForm";
import { api } from "@/lib/api";
import { renderPage } from "@/test/harness";

const SPECS: ServiceSpec[] = [
  {
    key: "plex",
    label: "Plex",
    fields: [
      { name: "base_url", label: "Server URL" },
      { name: "token", label: "X-Plex-Token", secret: true },
    ],
  },
  {
    key: "tmdb",
    label: "TMDB",
    fields: [{ name: "api_key", label: "API key", secret: true }],
  },
];

beforeEach(() => {
  vi.restoreAllMocks();
});

function saved(connections: Record<string, Record<string, unknown>>) {
  return { connections, unreadable: {} };
}

describe("saving connections", () => {
  it("sends what was typed", async () => {
    const save = vi.spyOn(api, "saveConfig").mockResolvedValue(saved({}) as never);

    renderPage(<ConnectionsForm specs={SPECS} initial={{}} />);
    await userEvent.type(screen.getByLabelText(/server url/i), "http://plex.local:32400");
    await userEvent.type(screen.getByLabelText(/x-plex-token/i), "secret-token");
    await userEvent.click(screen.getByRole("button", { name: /save connections/i }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    const payload = save.mock.calls[0][0] as Record<string, Record<string, unknown>>;
    expect(payload.plex).toEqual({
      base_url: "http://plex.local:32400",
      token: "secret-token",
    });
  });

  it("omits a blank field so an already-saved key survives the save", async () => {
    // The pin this file exists for. A saved secret comes back as `token_set:
    // true` with no value — there is nothing to re-type, and sending "" would
    // tell the server to clear it. Editing the Plex URL must not silently
    // delete the Plex token, or the TMDB key sitting untouched beside it.
    const save = vi.spyOn(api, "saveConfig").mockResolvedValue(saved({}) as never);

    renderPage(
      <ConnectionsForm
        specs={SPECS}
        initial={{ plex: { base_url: "http://old:32400", token_set: true }, tmdb: { api_key_set: true } }}
      />,
    );
    await userEvent.clear(screen.getByLabelText(/server url/i));
    await userEvent.type(screen.getByLabelText(/server url/i), "http://new:32400");
    await userEvent.click(screen.getByRole("button", { name: /save connections/i }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    const payload = save.mock.calls[0][0] as Record<string, Record<string, unknown>>;
    expect(payload.plex).toEqual({ base_url: "http://new:32400" });
    expect(payload.plex).not.toHaveProperty("token");
    expect(payload.tmdb).toEqual({});
  });

  it("NEGATIVE CONTROL: clearing a service sends explicit blanks", async () => {
    // The one path where an empty string is the message rather than the absence
    // of one. Without it there would be no way to remove a dead URL or a
    // rotated key from the UI at all.
    const save = vi.spyOn(api, "saveConfig").mockResolvedValue(saved({}) as never);

    renderPage(
      <ConnectionsForm specs={SPECS} initial={{ plex: { base_url: "http://old", token_set: true } }} />,
    );
    const clear = screen.getByRole("button", { name: /clear saved/i });
    await userEvent.click(clear);
    await userEvent.click(await screen.findByRole("button", { name: /really clear/i }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0]).toEqual({ plex: { base_url: "", token: "" } });
  });

  it("does not leave typed secrets in memory after a successful save", async () => {
    // The field is re-rendered from the masked server response, so anything left
    // in component state is a copy of a secret with no reason to exist.
    vi.spyOn(api, "saveConfig").mockResolvedValue(saved({}) as never);

    renderPage(<ConnectionsForm specs={SPECS} initial={{}} />);
    const token = screen.getByLabelText(/x-plex-token/i) as HTMLInputElement;
    await userEvent.type(token, "secret-token");
    await userEvent.click(screen.getByRole("button", { name: /save connections/i }));

    await screen.findByRole("button", { name: /saved/i });
    expect(token.value).toBe("");
  });

  it("NEGATIVE CONTROL: a failed save says so instead of showing Saved", async () => {
    // "Saved ✓" over a save that did not happen is the report this whole file is
    // named after, arriving by a different route.
    vi.spyOn(api, "saveConfig").mockRejectedValue(new Error("database is not accepting writes"));

    renderPage(<ConnectionsForm specs={SPECS} initial={{}} />);
    await userEvent.type(screen.getByLabelText(/server url/i), "http://plex.local:32400");
    await userEvent.click(screen.getByRole("button", { name: /save connections/i }));

    expect(await screen.findByText(/database is not accepting writes/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /saved ✓/i })).not.toBeInTheDocument();
  });
});

describe("testing a connection", () => {
  it("probes the unsaved values and reports the result", async () => {
    const test = vi.spyOn(api, "testConfig").mockResolvedValue({
      service: "plex",
      ok: true,
      detail: "Plex 1.40",
      latency_ms: 12,
    } as never);

    renderPage(<ConnectionsForm specs={SPECS} initial={{}} />);
    await userEvent.type(screen.getByLabelText(/server url/i), "http://plex.local:32400");
    await userEvent.click(screen.getAllByRole("button", { name: /^test$/i })[0]);

    expect(test).toHaveBeenCalledWith("plex", { base_url: "http://plex.local:32400" });
    expect(await screen.findByText(/Plex 1.40/)).toBeInTheDocument();
  });

  it("NEGATIVE CONTROL: a thrown request is reported, not swallowed", async () => {
    // The Test button exists to answer a question. A request that throws and
    // leaves the button in its resting state answers it wrongly, and the reading
    // most people take from silence is "fine".
    vi.spyOn(api, "testConfig").mockRejectedValue(new Error("network down"));

    renderPage(<ConnectionsForm specs={SPECS} initial={{}} />);
    await userEvent.type(screen.getByLabelText(/server url/i), "http://plex.local:32400");
    await userEvent.click(screen.getAllByRole("button", { name: /^test$/i })[0]);

    expect(await screen.findByText(/test failed/i)).toBeInTheDocument();
  });
});
