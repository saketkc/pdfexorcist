export async function get(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r;
}

export const bytes = async (url) => new Uint8Array(await (await get(url)).arrayBuffer());

/** falls back when the server does not send application/wasm */
export async function wasm(url) {
  try {
    return await WebAssembly.compileStreaming(get(url));
  } catch (e) {
    if (!(e instanceof TypeError)) throw e;
    return WebAssembly.compile(await bytes(url));
  }
}
