/** for py/pypdfium2.py; synchronous, so Python can call it mid-run */
export function pdfiumBridge(m) {
  m._FPDF_InitLibrary();
  const docs = new Map(); // handle -> its bytes' pointer, freed on close
  const scratch = (bytes, fn) => {
    const ptr = m._malloc(bytes);
    try {
      return fn(ptr);
    } finally {
      m._free(ptr);
    }
  };
  return {
    open(bytes) {
      const ptr = m._malloc(bytes.length);
      m.HEAPU8.set(bytes, ptr);
      const doc = m._FPDF_LoadMemDocument(ptr, bytes.length, 0);
      if (!doc) {
        m._free(ptr);
        throw new Error(`PDFium could not open the PDF (error ${m._FPDF_GetLastError()})`);
      }
      docs.set(doc, ptr);
      return doc;
    },
    closeDoc(doc) {
      m._FPDF_CloseDocument(doc);
      m._free(docs.get(doc));
      docs.delete(doc);
    },
    pageCount: (doc) => m._FPDF_GetPageCount(doc),
    loadPage(doc, i) {
      const page = m._FPDF_LoadPage(doc, i);
      if (!page) throw new Error(`PDFium could not load page ${i + 1}`);
      return page;
    },
    closePage: (page) => m._FPDF_ClosePage(page),
    pageHeight: (page) => m._FPDF_GetPageHeightF(page),
    pageWidth: (page) => m._FPDF_GetPageWidthF(page),
    formType: (doc) => m._FPDF_GetFormType(doc),
    /** pypdfium2's defaults: BGR on white, annotations drawn */
    render(page, width, height, rgba = false) {
      // BGRA plus REVERSE_BYTE_ORDER gives RGBA for ImageData
      const [format, flags] = rgba ? [4, 0x01 | 0x10] : [2, 0x01];
      const bmp = m._FPDFBitmap_CreateEx(width, height, format, 0, 0);
      if (!bmp) throw new Error(`PDFium could not allocate a ${width} x ${height} bitmap`);
      try {
        m._FPDFBitmap_FillRect(bmp, 0, 0, width, height, 0xffffffff | 0);
        m._FPDF_RenderPageBitmap(bmp, page, 0, 0, width, height, 0, flags);
        const stride = m._FPDFBitmap_GetStride(bmp);
        const buf = m._FPDFBitmap_GetBuffer(bmp);
        return [stride, m.HEAPU8.slice(buf, buf + stride * height)];
      } finally {
        m._FPDFBitmap_Destroy(bmp);
      }
    },
    bbox: (page) =>
      scratch(16, (ptr) => {
        // FS_RECTF is (l, t, r, b); pypdfium2 returns (l, b, r, t)
        m._FPDF_GetPageBoundingBox(page, ptr);
        const [l, t, r, b] = m.HEAPF32.slice(ptr / 4, ptr / 4 + 4);
        return [l, b, r, t];
      }),
    textPage(page) {
      const tp = m._FPDFText_LoadPage(page);
      if (!tp) throw new Error('PDFium could not read the page text');
      return tp;
    },
    closeTextPage: (tp) => m._FPDFText_ClosePage(tp),
    countRects: (tp) => m._FPDFText_CountRects(tp, 0, -1),
    rect: (tp, i) =>
      scratch(32, (ptr) => {
        if (!m._FPDFText_GetRect(tp, i, ptr, ptr + 8, ptr + 16, ptr + 24)) {
          throw new Error('Failed to get rectangle.');
        }
        const [l, t, r, b] = m.HEAPF64.slice(ptr / 8, ptr / 8 + 4);
        return [l, b, r, t];
      }),
    boundedText(tp, left, top, right, bottom) {
      const n = m._FPDFText_GetBoundedText(tp, left, top, right, bottom, 0, 0);
      if (n <= 0) return '';
      return scratch(2 * n, (ptr) => {
        m._FPDFText_GetBoundedText(tp, left, top, right, bottom, ptr, n);
        return utf16Ignore(m.HEAPU16.slice(ptr / 2, ptr / 2 + n));
      });
    },
  };
}

/** like pypdfium2: drops lone surrogates where TextDecoder would insert U+FFFD */
function utf16Ignore(units) {
  let s = '';
  for (let i = 0; i < units.length; i++) {
    const u = units[i];
    if (u >= 0xd800 && u < 0xdc00 && units[i + 1] >= 0xdc00 && units[i + 1] < 0xe000) {
      s += String.fromCharCode(u, units[++i]);
    } else if (u < 0xd800 || u >= 0xe000) {
      s += String.fromCharCode(u);
    }
  }
  return s;
}

export const ls = (FS, dir) => FS.readdir(dir).filter((n) => n !== '.' && n !== '..');

/** instantiateWasm hook that reuses a compiled module */
export const withModule = (module) => (imports, ready) => {
  WebAssembly.instantiate(module, imports).then((inst) => ready(inst, module));
  return {};
};

/** program({args, env, stage}) -> [code, out, err, FS]; files left in cwd come back */
export function programRunner(programs) {
  return async (name, args, files, cwd, env) => {
    const stage = (FS) => {
      for (const [path, data] of files) {
        FS.mkdirTree(path.slice(0, path.lastIndexOf('/')) || '/');
        FS.writeFile(path, data);
      }
      FS.mkdirTree(cwd);
      FS.chdir(cwd);
    };
    const [code, out, err, FS] = await programs[name]({ args, env, stage });
    return [code, out, err, walk(FS, cwd)];
  };
}

function walk(FS, dir) {
  return ls(FS, dir).flatMap((n) => {
    const path = `${dir}/${n}`.replace(/\/+/g, '/');
    return FS.isDir(FS.stat(path).mode) ? walk(FS, path) : [[path, FS.readFile(path)]];
  });
}

/** fresh instance per run: pdftotext keeps state in statics; exit() flushes stdout */
export function emscriptenProgram(factory, module) {
  return async ({ args, stage }) => {
    const out = [];
    const err = [];
    let code = 0;
    const m = await factory({
      instantiateWasm: withModule(module),
      preRun: [
        (mod) => mod.FS.init(null, (c) => c !== null && out.push(c), (c) => c !== null && err.push(c)),
      ],
      quit: (status) => {
        code = status;
      },
    });
    stage(m.FS);
    try {
      code = m.callMain(args) ?? code;
    } catch (e) {
      if (e?.name !== 'ExitStatus') throw e;
      code = e.status;
    }
    return [code, Uint8Array.from(out), Uint8Array.from(err), m.FS];
  };
}
