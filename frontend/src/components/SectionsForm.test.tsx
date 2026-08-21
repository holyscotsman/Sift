// The one screen that decides what Sift reads as a film.
//
// At 31% coverage, and it is the highest-consequence form in the app: a Home
// Videos library that Plex calls a "movie" library goes into the removal queue,
// the film counts, and the size baselines every verdict is measured against.
// The backend route behind Save was returning a 500 on every attempt and nothing
// noticed, because neither side had a test.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SectionsForm } from "@/components/SectionsForm";
import { api } from "@/lib/api";
import { renderPage } from "@/test/harness";

// Fields named as `SectionPlan` names them.
function section(overrides: Record<string, unknown> = {}) {
  return {
    key: "1",
    title: "Movies",
    plex_type: "movie",
    agent: "tv.plex.agents.movie",
    kind: "movie",
    reason: "Plex says films and it has a film agent.",
    overridden: false,
    ...overrides,
  };
}

const HOME_VIDEOS = section({
  key: "4",
  title: "Home Videos",
  kind: "ignore",
  agent: null,
  reason: "No metadata agent — skipped by default.",
});

describe("SectionsForm", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows what Plex calls each library and what Sift will do with it", async () => {
    vi.spyOn(api, "sections").mockResolvedValue({
      sections: [section(), HOME_VIDEOS],
      detail: "",
    });

    renderPage(<SectionsForm />);

    await screen.findByText("Home Videos");
    // Both facts, side by side: the disagreement is the whole point of the screen.
    // Plex calls *both* of these movie libraries, which is exactly why the second
    // fact — the missing agent — has to be on screen too.
    expect(screen.getAllByText(/Plex calls it a movie library/).length).toBe(2);
    expect(screen.getByText(/No metadata agent/)).toBeTruthy();
    // And the verdict, as a pill. "Ignore" is not one of the button labels for
    // any other row, so this is the pill on Home Videos.
    const pills = screen.getAllByText("Ignore");
    expect(pills.some((el) => el.tagName !== "BUTTON")).toBe(true);
  });

  it("marks the current choice as pressed, not merely styled", async () => {
    vi.spyOn(api, "sections").mockResolvedValue({
      sections: [HOME_VIDEOS],
      detail: "",
    });

    renderPage(<SectionsForm />);
    await screen.findByText("Home Videos");

    const group = screen.getByRole("group", { name: "Home Videos" });
    const pressed = group.querySelectorAll('[aria-pressed="true"]');
    expect(pressed.length).toBe(1);
    expect(pressed[0].textContent).toBe("Ignore");
  });

  it("cannot save until something changes", async () => {
    vi.spyOn(api, "sections").mockResolvedValue({ sections: [section()], detail: "" });
    const save = vi.spyOn(api, "saveSections");

    renderPage(<SectionsForm />);
    await screen.findByText("Movies");

    const button = screen.getByRole("button", { name: /save libraries/i });
    expect(button.hasAttribute("disabled")).toBe(true);

    await userEvent.click(screen.getByRole("button", { name: "TV" }));
    await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
    expect(save).not.toHaveBeenCalled(); // nothing is sent until Save is pressed
  });

  it("sends the whole map, not only what the user touched", async () => {
    // The comment in `save()` is the reason this exists: an override set back to
    // Plex's own answer still has to be transmitted, or the previous override
    // sticks on the server and the screen lies about what Sift will read.
    vi.spyOn(api, "sections").mockResolvedValue({
      sections: [
        section({ key: "1", title: "Movies" }),
        section({ key: "2", title: "Old Override", kind: "ignore", overridden: true }),
        section({ key: "3", title: "Untouched" }),
      ],
      detail: "",
    });
    const save = vi.spyOn(api, "saveSections").mockResolvedValue({
      sections: [section()],
      detail: "",
    });

    renderPage(<SectionsForm />);
    await screen.findByText("Movies");

    await userEvent.click(
      screen.getByRole("group", { name: "Movies" }).querySelector('[aria-pressed="false"]')!,
    );
    await userEvent.click(screen.getByRole("button", { name: /save libraries/i }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    const sent = save.mock.calls[0][0] as Record<string, string>;
    expect(sent["Movies"]).toBe("show"); // the edit
    expect(sent["Old Override"]).toBe("ignore"); // the existing override, resent
    expect(sent["Untouched"]).toBeUndefined(); // never overridden, nothing to say
  });

  it("takes the server's answer as the new truth after saving", async () => {
    vi.spyOn(api, "sections").mockResolvedValue({ sections: [section()], detail: "" });
    vi.spyOn(api, "saveSections").mockResolvedValue({
      sections: [section({ title: "Movies", kind: "show", overridden: true })],
      detail: "",
    });

    renderPage(<SectionsForm />);
    await screen.findByText("Movies");

    await userEvent.click(screen.getByRole("button", { name: "TV" }));
    await userEvent.click(screen.getByRole("button", { name: /save libraries/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /save libraries/i }).hasAttribute("disabled")).toBe(
        true,
      ),
    );
    // Re-disabled means `pending` was cleared, which only happens on success.
    // The row now reads TV from the server's answer, not from a pending edit:
    // the pill is the non-button "TV" on screen.
    const shown = screen.getAllByText("TV");
    expect(shown.some((el) => el.tagName !== "BUTTON")).toBe(true);
  });

  it("says so when the save fails and keeps the edit", async () => {
    // NEGATIVE CONTROL for the above. The route behind this returned a 500 on
    // every single attempt for as long as it existed. A form that silently
    // cleared its pending edits on failure would have shown the user a saved
    // state that never reached the server.
    vi.spyOn(api, "sections").mockResolvedValue({ sections: [section()], detail: "" });
    vi.spyOn(api, "saveSections").mockRejectedValue(new Error("Server error"));

    renderPage(<SectionsForm />);
    await screen.findByText("Movies");

    await userEvent.click(screen.getByRole("button", { name: "TV" }));
    await userEvent.click(screen.getByRole("button", { name: /save libraries/i }));

    await screen.findByText("Server error");
    // Still dirty: the edit survived, so pressing Save again retries it.
    expect(
      screen.getByRole("button", { name: /save libraries/i }).hasAttribute("disabled"),
    ).toBe(false);
  });

  it("explains itself when Plex cannot be read", async () => {
    vi.spyOn(api, "sections").mockRejectedValue(new Error("connection refused"));

    renderPage(<SectionsForm />);

    await screen.findByText(/Couldn't read your Plex libraries/);
    // No skeleton left spinning, and no empty panel pretending there are none.
    expect(screen.queryByRole("button", { name: /save libraries/i })).toBeNull();
  });

  it("distinguishes a library with none from a Plex it could not reach", async () => {
    // NEGATIVE CONTROL for the above: an empty list is a real answer and must not
    // render as an error, or somebody with no libraries goes looking for a
    // connection fault that does not exist.
    vi.spyOn(api, "sections").mockResolvedValue({
      sections: [],
      detail: "Plex reported no libraries.",
    });

    renderPage(<SectionsForm />);

    await screen.findByText("Plex reported no libraries.");
    expect(screen.queryByText(/Couldn't read/)).toBeNull();
  });

  it("shows a busy state rather than an empty panel while loading", async () => {
    vi.spyOn(api, "sections").mockReturnValue(new Promise(() => {}));

    const { container } = renderPage(<SectionsForm />);

    expect(container.querySelector('[aria-busy="true"]')).toBeTruthy();
  });
});
