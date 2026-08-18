// This dialog stands in front of every irreversible action in the app.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ConfirmModal } from "@/components/ConfirmModal";

function open(props: Partial<Parameters<typeof ConfirmModal>[0]> = {}) {
  return render(
    <ConfirmModal
      open
      title="Approve removal of 1 title?"
      body={<p>The Matrix</p>}
      confirmLabel="Approve & remove"
      onConfirm={vi.fn()}
      onCancel={vi.fn()}
      {...props}
    />,
  );
}

describe("focus", () => {
  it("lands on Cancel, never on the destructive button", () => {
    open();
    // A stray Enter or Space arriving on an autofocused Confirm approves a
    // deletion nobody chose. The safe option is the one keypress away.
    expect(screen.getByRole("button", { name: /cancel/i })).toHaveFocus();
    expect(screen.getByRole("button", { name: /approve/i })).not.toHaveFocus();
  });

  it("means Enter on open cancels rather than deletes", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    open({ onConfirm, onCancel });

    await userEvent.keyboard("{Enter}");

    expect(onConfirm).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalled();
  });

  it("is trapped inside the dialog", async () => {
    open();
    const cancel = screen.getByRole("button", { name: /cancel/i });
    const confirm = screen.getByRole("button", { name: /approve/i });

    await userEvent.tab();
    expect(confirm).toHaveFocus();
    // Tab used to walk straight out into the page behind — a modal that blocks
    // visually but not actually.
    await userEvent.tab();
    expect(cancel).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(confirm).toHaveFocus();
  });

  it("returns focus to whatever opened it", async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>Approve removal</button>
          <ConfirmModal
            open={open}
            title="Sure?"
            body={<p>x</p>}
            onConfirm={() => setOpen(false)}
            onCancel={() => setOpen(false)}
          />
        </>
      );
    }
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Approve removal" });
    await userEvent.click(opener);
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));

    // Otherwise a keyboard user working down a queue lands on <body> and tabs
    // from the top of the page after every single decision.
    expect(opener).toHaveFocus();
  });
});

describe("NEGATIVE CONTROL: the dialog still works", () => {
  it("confirms when Confirm is actually pressed", async () => {
    const onConfirm = vi.fn();
    open({ onConfirm });

    // Focusing Cancel must not mean the destructive path became unreachable —
    // that would pass every test above and ship a dialog that cannot approve.
    await userEvent.click(screen.getByRole("button", { name: /approve/i }));

    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
