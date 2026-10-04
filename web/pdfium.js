
import { pdfiumBridge, withModule } from './engines.js';
import { get } from './net.js';

const MAX_PIXELS = 4096 * 4096; // per page; a huge MediaBox would exhaust memory

/** first message {pdfium: module}; then answer(msg) -> [result, transfer], {cancel: id} -> cancel */
export function serve(answer, cancel = () => {}) {
  let start;
  const ready = new Promise((resolve) => {
    start = resolve;
  });
  onmessage = async ({ data: msg }) => {
    if (msg.pdfium) return start(instantiate(msg.pdfium));
    if ('cancel' in msg) return cancel(msg.cancel);
    try {
      await ready;
      const [res, transfer] = await answer(msg);
      postMessage({ id: msg.id, ok: true, ...res }, transfer ?? []);
    } catch (e) {
      postMessage({ id: msg.id, ok: false, message: String(e?.message ?? e) });
    }
  };
  return ready;
}

async function instantiate(module) {
  const script = await (await get('vendor/pdfium.cjs')).text();
  // classic Emscripten script: uses the global Module for its lifetime
  const ready = new Promise((resolve) => {
    globalThis.Module = {
      instantiateWasm: withModule(module),
      onRuntimeInitialized: resolve,
    };
  });
  (0, eval)(script);
  await ready;
  globalThis.pdfium = pdfiumBridge(globalThis.Module);
}

export async function renderPage(doc, i, width) {
  const b = globalThis.pdfium;
  const page = b.loadPage(doc, i);
  try {
    const [pw, ph] = [b.pageWidth(page), b.pageHeight(page)];
    if (!(pw > 0 && ph > 0 && Number.isFinite(pw) && Number.isFinite(ph))) {
      throw new Error(`page ${i + 1} has no usable size (${pw} x ${ph} pt)`);
    }
    const scale = Math.min(width / pw, Math.sqrt(MAX_PIXELS / (pw * ph)));
    const w = Math.max(1, Math.ceil(pw * scale));
    const h = Math.max(1, Math.ceil(ph * scale));
    const [stride, rgba] = b.render(page, w, h, true); // 4-byte pixels: stride is 4 * w
    return createImageBitmap(new ImageData(new Uint8ClampedArray(rgba.buffer), stride / 4, h));
  } finally {
    b.closePage(page);
  }
}
