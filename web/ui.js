const nodes = (kids) => kids.flat(Infinity).filter((k) => k != null && k !== false);
export const el = (tag, props = {}, ...kids) => {
  const e = Object.assign(document.createElement(tag), props);
  e.append(...nodes(kids));
  return e;
};
export const fill = (parent, ...kids) => parent.replaceChildren(...nodes(kids));
export const button = (className, onclick, ...kids) => el('button', { className, type: 'button', onclick }, ...kids);
export const failure = (say, detail) => [el('p', { className: 'say' }, say), el('p', { className: 'sub error' }, detail)];
export const fmt = (n) => Number(n).toLocaleString('en-IN');
export const plural = (n, one, many = `${one}s`) => `${fmt(n)} ${n === 1 ? one : many}`;

/** closes the bitmap; the canvas keeps the pixels */
export function draw(bitmap) {
  const c = el('canvas', { width: bitmap.width, height: bitmap.height });
  c.getContext('2d').drawImage(bitmap, 0, 0);
  bitmap.close();
  return c;
}
export const minutes = (seconds) => plural(Math.max(1, Math.round(seconds / 60)), 'minute');
