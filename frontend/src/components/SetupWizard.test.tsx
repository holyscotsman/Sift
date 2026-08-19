// First run on a hosted deploy. The server requires the deploy's access token to
// create the first account — correctly, or whoever finds the hostname first gets
// it — and the wizard used to send only a username and a password, get a 401 it
// could not explain, and offer nowhere to put the token. On the deployment path
// this app is documented for, first run did not work.

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SetupWizard } from "@/components/SetupWizard";
import { api } from "@/lib/api";
import { renderPage } from "@/test/harness";

async function fillAccount() {
  await userEvent.type(screen.getByLabelText(/username/i), "owner");
  await userEvent.type(screen.getByLabelText(/^password/i), "hunter2hunter2");
  await userEvent.type(screen.getByLabelText(/confirm password/i), "hunter2hunter2");
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("a deploy that requires its access token", () => {
  it("asks for the token and sends it", async () => {
    vi.spyOn(api, "authStatus").mockResolvedValue({
      setup_complete: false,
      username: null,
      setup_requires_token: true,
    } as never);
    const setup = vi
      .spyOn(api, "authSetup")
      .mockResolvedValue({ token: "session", username: "owner" } as never);

    renderPage(<SetupWizard onComplete={() => {}} />);

    const field = await screen.findByLabelText(/deploy access token/i);
    await fillAccount();
    await userEvent.type(field, "deploy-secret");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(setup).toHaveBeenCalledWith("owner", "hunter2hunter2", "deploy-secret");
  });

  it("says what is missing rather than letting the server refuse", async () => {
    vi.spyOn(api, "authStatus").mockResolvedValue({
      setup_complete: false,
      username: null,
      setup_requires_token: true,
    } as never);
    const setup = vi.spyOn(api, "authSetup");

    renderPage(<SetupWizard onComplete={() => {}} />);
    await screen.findByLabelText(/deploy access token/i);
    await fillAccount();
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByText(/needs its access token/i)).toBeInTheDocument();
    expect(setup).not.toHaveBeenCalled();
  });
});

describe("NEGATIVE CONTROL: a local install with no token configured", () => {
  it("is not asked for a credential that does not exist", async () => {
    vi.spyOn(api, "authStatus").mockResolvedValue({
      setup_complete: false,
      username: null,
      setup_requires_token: false,
    } as never);
    const setup = vi
      .spyOn(api, "authSetup")
      .mockResolvedValue({ token: "session", username: "owner" } as never);

    renderPage(<SetupWizard onComplete={() => {}} />);
    await fillAccount();
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));

    // A field nobody can fill in is worse than no field.
    expect(screen.queryByLabelText(/deploy access token/i)).not.toBeInTheDocument();
    expect(setup).toHaveBeenCalledWith("owner", "hunter2hunter2", undefined);
  });
});
