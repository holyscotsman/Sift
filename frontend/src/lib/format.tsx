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
