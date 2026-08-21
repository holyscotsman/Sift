// Tiny answer formatter for Ask — NOT a markdown engine. Recognises exactly
// three things models actually emit: paragraphs, bullet/numbered list runs, and
// **bold** spans. Anything else renders as literal text, never dropped.

import type { ReactNode } from "react";

function inline(text: string, keyBase: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
      <strong key={`${keyBase}b${i}`} className="font-semibold text-fg">
        {part.slice(2, -2)}
      </strong>
    ) : (
      part
    ),
  );
}

export function formatAnswer(text: string): ReactNode[] {
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flushParagraph = () => {
    if (paragraph.length) {
      const key = `p${blocks.length}`;
      blocks.push(<p key={key}>{inline(paragraph.join(" "), key)}</p>);
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list) {
      const key = `l${blocks.length}`;
      const items = list.items.map((item, i) => (
        <li key={`${key}i${i}`}>{inline(item, `${key}i${i}`)}</li>
      ));
      blocks.push(
        list.ordered ? (
          <ol key={key} className="ml-5 list-decimal space-y-0.5">
            {items}
          </ol>
        ) : (
          <ul key={key} className="ml-5 list-disc space-y-0.5">
            {items}
          </ul>
        ),
      );
      list = null;
    }
  };

  for (const line of text.split("\n")) {
    const bullet = /^\s*[-*]\s+(.+)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
    if (bullet || numbered) {
      flushParagraph();
      const ordered = Boolean(numbered);
      if (!list || list.ordered !== ordered) {
        flushList();
        list = { ordered, items: [] };
      }
      list.items.push((bullet ?? numbered)![1]);
    } else if (line.trim() === "") {
      flushParagraph();
      flushList();
    } else {
      flushList();
      paragraph.push(line.trim());
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}

// ---------------------------------------------------------------------------
// Sizes.
//
// There were six copies of this and five of them could not express a file
// smaller than 50 MB: each went straight from bytes to
// `(bytes / 1e9).toFixed(1) + " GB"`, so a 40 MB sample rendered as "0.0 GB".
// That is not a rounding nicety on the Storage page — samples, trailers and
// part-downloads are *by definition* small, and they are the whole category
// tier 0 exists to reclaim. The one screen whose job is to report sizes could
// not name the sizes it most needed to.
//
// Found by looking at a rendered page. jsdom has no opinion about whether
// "0.0 GB" is a sensible thing to print, so every unit test was happy.

/** Bytes as the largest unit that keeps the number meaningful. `—` for nothing. */
export function fmtSize(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  const n = Math.abs(bytes);
  if (n >= 1e12) return `${(bytes / 1e12).toFixed(2)} TB`;
  if (n >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  // No decimal below a gigabyte: "847 MB" is the useful precision, and "846.7 MB"
  // is three digits nobody reads on a row that is one of two hundred.
  if (n >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
  return `${Math.round(bytes / 1e3)} KB`;
}
