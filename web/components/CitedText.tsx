"use client";

import React from "react";
import Link from "next/link";

// Incident prefixes used in the Sentinel platform
const INCIDENT_REGEX = /\b((?:INC|DRIFT|VOL|SCH|DFT|DEP|CHG|TRN|FRS|LBL|DUP|SKW)-\d+)\b/g;

/**
 * Parses inline markdown:
 * - Incident IDs: INC-xxxx, DRIFT-xxxx, etc. -> Clickable Link
 * - Bold: **text** or __text__
 * - Italic: *text* or _text_
 * - Inline code: `code`
 * - Markdown links: [text](url)
 */
function parseInline(text: string): React.ReactNode[] {
  // Regex to split by inline markdown tokens:
  // 1: `code`
  // 2: **bold** or __bold__
  // 3: *italic* or _italic_
  // 4: [link](url)
  // 5: INC-1234
  const tokenRegex =
    /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\([^)]+\)|\b(?:INC|DRIFT|VOL|SCH|DFT|DEP|CHG|TRN|FRS|LBL|DUP|SKW)-\d+\b)/g;

  const parts = text.split(tokenRegex);

  return parts.map((part, index) => {
    if (!part) return null;

    // 1. Inline code
    if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
      const code = part.slice(1, -1);
      // If the code is an incident ID, make it an incident link inside code style
      if (INCIDENT_REGEX.test(code)) {
        return (
          <Link
            key={index}
            href={`/incidents/${code}`}
            className="rounded border border-accent/30 bg-accent-soft px-1.5 py-0.5 font-mono text-xs font-semibold text-accent transition hover:border-accent hover:underline"
          >
            {code}
          </Link>
        );
      }
      return (
        <code
          key={index}
          className="rounded border border-border-strong bg-surface-raised px-1.5 py-0.5 font-mono text-xs text-foreground/90"
        >
          {code}
        </code>
      );
    }

    // 2. Bold
    if (
      (part.startsWith("**") && part.endsWith("**") && part.length >= 4) ||
      (part.startsWith("__") && part.endsWith("__") && part.length >= 4)
    ) {
      const inner = part.slice(2, -2);
      return (
        <strong key={index} className="font-semibold text-foreground">
          {parseInline(inner)}
        </strong>
      );
    }

    // 3. Italic
    if (
      (part.startsWith("*") && part.endsWith("*") && part.length >= 2) ||
      (part.startsWith("_") && part.endsWith("_") && part.length >= 2)
    ) {
      const inner = part.slice(1, -1);
      return (
        <em key={index} className="italic text-foreground/90">
          {parseInline(inner)}
        </em>
      );
    }

    // 4. Link
    const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (linkMatch) {
      const [, label, href] = linkMatch;
      const isExternal = href.startsWith("http://") || href.startsWith("https://");
      return (
        <Link
          key={index}
          href={href}
          target={isExternal ? "_blank" : undefined}
          rel={isExternal ? "noreferrer" : undefined}
          className="text-accent underline underline-offset-2 transition hover:text-accent-glow"
        >
          {label}
        </Link>
      );
    }

    // 5. Incident ID (raw text)
    if (/^(?:INC|DRIFT|VOL|SCH|DFT|DEP|CHG|TRN|FRS|LBL|DUP|SKW)-\d+$/.test(part)) {
      return (
        <Link
          key={index}
          href={`/incidents/${part}`}
          className="inline-flex items-center gap-1 rounded border border-accent/40 bg-accent-soft px-1.5 py-0.5 font-mono text-xs font-semibold text-accent transition hover:border-accent hover:bg-accent/20 hover:underline"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
          {part}
        </Link>
      );
    }

    return <React.Fragment key={index}>{part}</React.Fragment>;
  });
}

/**
 * Full Markdown Renderer for Sentinel Chat & Insights
 * Handles:
 * - Headings (#, ##, ###, ####)
 * - Code blocks (```lang ... ```)
 * - Blockquotes (> quote)
 * - Lists (- item, * item, 1. item)
 * - Tables (| col | col |)
 * - Paragraphs with full inline formatting and interactive incident links
 */
export default function CitedText({ text }: { text: string }) {
  if (!text) return null;

  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    // 1. Code block (```)
    if (line.trim().startsWith("```")) {
      const lang = line.trim().slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // consume closing ```
      elements.push(
        <div
          key={`code-${i}`}
          className="my-3 overflow-hidden rounded-lg border border-border bg-surface-raised"
        >
          {lang && (
            <div className="border-b border-border bg-surface px-3 py-1 text-[11px] font-mono text-muted-dim">
              {lang}
            </div>
          )}
          <pre className="max-h-96 overflow-x-auto p-3 font-mono text-xs leading-relaxed text-foreground scrollbar-thin">
            <code>{codeLines.join("\n")}</code>
          </pre>
        </div>,
      );
      continue;
    }

    // 2. Blockquote (> text)
    if (line.startsWith("> ") || line === ">") {
      const quoteLines: string[] = [line.replace(/^>\s?/, "")];
      i++;
      while (i < lines.length && (lines[i].startsWith("> ") || lines[i] === ">")) {
        quoteLines.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      elements.push(
        <blockquote
          key={`quote-${i}`}
          className="my-2 border-l-2 border-accent/60 bg-accent-soft/30 px-3 py-1.5 text-xs text-foreground/90 italic rounded-r"
        >
          {quoteLines.map((ql, qIdx) => (
            <p key={qIdx} className="leading-relaxed">
              {parseInline(ql)}
            </p>
          ))}
        </blockquote>,
      );
      continue;
    }

    // 3. Headings
    if (line.startsWith("# ")) {
      elements.push(
        <h1 key={`h1-${i}`} className="mt-4 mb-2 text-base font-bold text-foreground">
          {parseInline(line.slice(2))}
        </h1>,
      );
      i++;
      continue;
    }
    if (line.startsWith("## ")) {
      elements.push(
        <h2 key={`h2-${i}`} className="mt-3 mb-1.5 text-sm font-semibold text-foreground">
          {parseInline(line.slice(3))}
        </h2>,
      );
      i++;
      continue;
    }
    if (line.startsWith("### ")) {
      elements.push(
        <h3 key={`h3-${i}`} className="mt-2.5 mb-1 text-xs font-semibold uppercase tracking-wider text-muted">
          {parseInline(line.slice(4))}
        </h3>,
      );
      i++;
      continue;
    }

    // 4. Unordered List (- item or * item)
    if (/^\s*[-*]\s+/.test(line)) {
      const listItems: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        listItems.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i++;
      }
      elements.push(
        <ul key={`ul-${i}`} className="my-2 space-y-1.5 pl-4 text-xs leading-relaxed">
          {listItems.map((item, itemIdx) => (
            <li key={itemIdx} className="list-disc text-foreground/90">
              {parseInline(item)}
            </li>
          ))}
        </ul>,
      );
      continue;
    }

    // 5. Ordered List (1. item)
    if (/^\s*\d+\.\s+/.test(line)) {
      const listItems: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        listItems.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i++;
      }
      elements.push(
        <ol key={`ol-${i}`} className="my-2 space-y-1.5 pl-4 text-xs leading-relaxed list-decimal">
          {listItems.map((item, itemIdx) => (
            <li key={itemIdx} className="text-foreground/90">
              {parseInline(item)}
            </li>
          ))}
        </ol>,
      );
      continue;
    }

    // 6. Horizontal Rule (---, ***, ___)
    if (/^(\*{3,}|-{3,}|_{3,})$/.test(line.trim())) {
      elements.push(<hr key={`hr-${i}`} className="my-3 border-border" />);
      i++;
      continue;
    }

    // 7. Empty line
    if (!line.trim()) {
      elements.push(<div key={`space-${i}`} className="h-1.5" />);
      i++;
      continue;
    }

    // 8. Regular paragraph
    elements.push(
      <p key={`p-${i}`} className="my-1 text-xs leading-relaxed text-foreground/90">
        {parseInline(line)}
      </p>,
    );
    i++;
  }

  return <div className="space-y-0.5">{elements}</div>;
}
