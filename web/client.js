// a dead worker is replaced and its pending requests fail

export class Client {
  /** init() resolves to the first message each worker gets, replacements included */
  constructor(file, { onStatus, init } = {}) {
    Object.assign(this, { file, onStatus, init, pending: new Map(), next: 0, generation: 0 });
    this.start();
  }

  start() {
    this.generation++;
    this.onStatus?.({ type: 'restart' });
    const worker = (this.worker = new Worker(new URL(this.file, import.meta.url), { type: 'module' }));
    this.ready = Promise.resolve(this.init?.()).then((first) => first && worker.postMessage(first));
    worker.onmessage = ({ data }) => {
      if (!('id' in data)) return this.onStatus?.(data);
      const p = this.pending.get(data.id);
      if (!p) return data.pages?.forEach((b) => b.close()); // aborted: free its bitmaps
      if (data.type === 'progress') return p.progress?.(data);
      this.pending.delete(data.id);
      if (data.ok) p.resolve(data);
      else p.reject(new Error(data.message));
    };
    worker.onerror = (e) => this.restart(new Error(`The engines stopped: ${e.message || 'out of memory?'}`));
    worker.onmessageerror = () => this.restart(new Error('A message from the engines could not be read.'));
  }

  /** aborting rejects the request and cancels it in the worker if it has not started */
  async ask(msg, { signal, progress } = {}) {
    await this.ready;
    signal?.throwIfAborted();
    const id = this.next++;
    const worker = this.worker;
    return new Promise((resolve, reject) => {
      const abort = () => {
        this.pending.delete(id);
        worker.postMessage({ cancel: id });
        reject(signal.reason);
      };
      signal?.addEventListener('abort', abort, { once: true });
      const settle = (f) => (v) => {
        signal?.removeEventListener('abort', abort);
        f(v);
      };
      this.pending.set(id, { resolve: settle(resolve), reject: settle(reject), progress });
      worker.postMessage({ ...msg, id });
    });
  }

  restart(reason) {
    this.worker.terminate();
    for (const p of this.pending.values()) p.reject(reason);
    this.pending.clear();
    this.start();
  }
}
