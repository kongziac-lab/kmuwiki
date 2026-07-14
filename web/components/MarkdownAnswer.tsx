"use client";

import type { ReactNode } from "react";

export function MarkdownAnswer({ text }: { text: string }) {
  return <div className="answer answer-markdown">{renderBlocks(text)}</div>;
}

function renderBlocks(text: string): ReactNode[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const nodes: ReactNode[] = [];
  let index = 0;
  let key = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (!line.trim()) {
      index += 1;
      continue;
    }

    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      const Tag = heading[1].length >= 3 ? "h4" : "h3";
      nodes.push(<Tag key={key++}>{renderInline(heading[2].trim())}</Tag>);
      index += 1;
      continue;
    }

    if (isTableStart(lines, index)) {
      const table = readTable(lines, index);
      nodes.push(renderTable(table.header, table.rows, key++));
      index = table.nextIndex;
      continue;
    }

    if (isUnorderedList(line)) {
      const items: string[] = [];
      while (index < lines.length && isUnorderedList(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, "").trim());
        index += 1;
      }
      nodes.push(
        <ul key={key++}>
          {items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item)}</li>)}
        </ul>,
      );
      continue;
    }

    if (isOrderedList(line)) {
      const items: string[] = [];
      while (index < lines.length && isOrderedList(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+[.)]\s+/, "").trim());
        index += 1;
      }
      nodes.push(
        <ol key={key++}>
          {items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item)}</li>)}
        </ol>,
      );
      continue;
    }

    const paragraph: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^(#{1,4})\s+/.test(lines[index]) &&
      !isTableStart(lines, index) &&
      !isUnorderedList(lines[index]) &&
      !isOrderedList(lines[index])
    ) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    nodes.push(<p key={key++}>{renderInline(paragraph.join(" "))}</p>);
  }

  return nodes;
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])/g;
  let lastIndex = 0;
  let key = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    const token = match[0];
    if (token.startsWith("**")) {
      nodes.push(<strong key={key++}>{renderInline(token.slice(2, -2))}</strong>);
    } else if (token.startsWith("`")) {
      nodes.push(<code key={key++}>{token.slice(1, -1)}</code>);
    } else {
      nodes.push(<span className="answer-citation" key={key++}>{token}</span>);
    }

    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
}

function isUnorderedList(line: string): boolean {
  return /^\s*[-*]\s+/.test(line);
}

function isOrderedList(line: string): boolean {
  return /^\s*\d+[.)]\s+/.test(line);
}

function isTableStart(lines: string[], index: number): boolean {
  return Boolean(
    lines[index]?.includes("|") &&
    lines[index + 1]?.includes("|") &&
    isTableDelimiter(lines[index + 1]),
  );
}

function isTableDelimiter(line: string): boolean {
  const cells = splitTableRow(line);
  return cells.length >= 2 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, "")));
}

function readTable(lines: string[], startIndex: number) {
  const header = splitTableRow(lines[startIndex]);
  const rows: string[][] = [];
  let index = startIndex + 2;

  while (index < lines.length && lines[index].trim() && lines[index].includes("|")) {
    rows.push(padRow(splitTableRow(lines[index]), header.length));
    index += 1;
  }

  return { header, rows, nextIndex: index };
}

function splitTableRow(line: string): string[] {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function padRow(row: string[], length: number): string[] {
  if (row.length >= length) return row.slice(0, length);
  return [...row, ...Array.from({ length: length - row.length }, () => "")];
}

function renderTable(header: string[], rows: string[][], key: number) {
  return (
    <div className="answer-table-wrap" key={key}>
      <table className="answer-table">
        <thead>
          <tr>{header.map((cell, index) => <th key={index}>{renderInline(cell)}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => <td key={cellIndex}>{renderInline(cell)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
