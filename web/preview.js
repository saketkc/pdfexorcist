// in: {open: pdf} -> {doc, count}; {doc, first, max, width} -> {pages}; {close: doc}
// documents stay open so more pages skip re-sending and re-parsing the PDF

import { renderPage, serve } from './pdfium.js';

serve(async (msg) => {
  const b = globalThis.pdfium;
  if (msg.open) {
    const doc = b.open(msg.open);
    return [{ doc, count: b.pageCount(doc) }];
  }
  if (msg.close) return [b.closeDoc(msg.close)];
  const pages = [];
  try {
    const last = Math.min(b.pageCount(msg.doc), msg.first + msg.max);
    for (let i = msg.first; i < last; i++) pages.push(await renderPage(msg.doc, i, msg.width));
    return [{ pages }, pages];
  } catch (e) {
    for (const p of pages) p.close();
    throw e;
  }
});
