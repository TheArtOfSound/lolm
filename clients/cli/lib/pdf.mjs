// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Small, dependency-free text/Markdown to PDF writer for guaranteed local output. */
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

function ascii(value) {
  return String(value || "").normalize("NFKD").replace(
    /[^\x20-\x7E\n]/g,
    (char) => ({ "•": "-", "—": "-", "–": "-", "“": '"', "”": '"', "’": "'" }[char] || "?"),
  );
}
function esc(value) { return value.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)"); }
function wrap(text, width) {
  const words = text.trim().split(/\s+/).filter(Boolean), lines = [];
  let line = "";
  for (const word of words) {
    if (!line) line = word;
    else if (`${line} ${word}`.length <= width) line += ` ${word}`;
    else { lines.push(line); line = word; }
  }
  if (line) lines.push(line);
  return lines.length ? lines : [""];
}

function layout(markdown, title) {
  const blocks = [];
  if (title) blocks.push({ text: title, size: 20, leading: 27, bold: true, gap: 12 });
  for (const raw of ascii(markdown).split("\n")) {
    const heading = raw.match(/^(#{1,3})\s+(.*)$/);
    if (heading) {
      const size = heading[1].length === 1 ? 18 : heading[1].length === 2 ? 15 : 12;
      blocks.push({ text: heading[2], size, leading: size + 6, bold: true, gap: 7 });
      continue;
    }
    const bullet = raw.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) blocks.push({ text: `- ${bullet[1]}`, size: 10.5, leading: 15, indent: 12, gap: 2 });
    else if (!raw.trim()) blocks.push({ text: "", size: 10.5, leading: 10, gap: 0 });
    else blocks.push({ text: raw.replace(/\*\*/g, "").replace(/`/g, ""), size: 10.5, leading: 15, gap: 3 });
  }
  return blocks;
}

export async function createPdf(markdown, outPath, { title = "" } = {}) {
  const width = 612, height = 792, margin = 54;
  const pages = [[]];
  let y = height - margin;
  for (const block of layout(markdown, title)) {
    const chars = Math.max(24, Math.floor((width - margin * 2 - (block.indent || 0)) / (block.size * 0.52)));
    const lines = wrap(block.text, chars);
    const needed = lines.length * block.leading + block.gap;
    if (y - needed < margin) { pages.push([]); y = height - margin; }
    for (const line of lines) {
      pages.at(-1).push({ ...block, text: line, y });
      y -= block.leading;
    }
    y -= block.gap;
  }

  const objects = [];
  const pageRefs = [];
  const add = (body) => { objects.push(body); return objects.length; };
  const catalog = add("");
  const pagesRef = add("");
  const regularFont = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
  const boldFont = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>");
  for (const page of pages) {
    const stream = page.map((line) => `BT /F${line.bold ? 2 : 1} ${line.size} Tf 1 0 0 1 ${margin + (line.indent || 0)} ${line.y.toFixed(2)} Tm (${esc(line.text)}) Tj ET`).join("\n");
    const content = add(`<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`);
    const pageRef = add(`<< /Type /Page /Parent ${pagesRef} 0 R /MediaBox [0 0 ${width} ${height}] /Resources << /Font << /F1 ${regularFont} 0 R /F2 ${boldFont} 0 R >> >> /Contents ${content} 0 R >>`);
    pageRefs.push(pageRef);
  }
  objects[catalog - 1] = `<< /Type /Catalog /Pages ${pagesRef} 0 R >>`;
  objects[pagesRef - 1] = `<< /Type /Pages /Kids [${pageRefs.map((ref) => `${ref} 0 R`).join(" ")}] /Count ${pageRefs.length} >>`;
  let pdf = "%PDF-1.7\n%LOLM\n";
  const offsets = [0];
  for (let index = 0; index < objects.length; index++) {
    offsets.push(Buffer.byteLength(pdf));
    pdf += `${index + 1} 0 obj\n${objects[index]}\nendobj\n`;
  }
  const xref = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  pdf += offsets.slice(1).map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root ${catalog} 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  const path = resolve(outPath);
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, Buffer.from(pdf, "ascii"));
  return { path, bytes: Buffer.byteLength(pdf), pages: pages.length };
}
