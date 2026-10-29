/** Images loaded and decoded before they are shown. `keep(urls)` starts loading those not yet loading and lets go of
 *  the rest, which stops their loading and bounds memory to the window. */
export function imagesAhead() {
  const held = new Map<string, HTMLImageElement>();
  return {
    keep(urls: string[]) {
      const wanted = new Set(urls);
      for (const url of wanted) {
        if (held.has(url)) continue;
        const image = new Image();
        image.src = url;
        image.decode().catch(() => { /* Shown as a failure, if at all, when it is opened. */ });
        held.set(url, image);
      }
      for (const [url, image] of held) if (!wanted.has(url)) { image.src = ''; held.delete(url); }
    },
    clear() { this.keep([]); },
  };
}

/** One request per key, shared by everyone who asks until the cache is dropped. A failed request is forgotten, so
 *  the next ask tries again. */
export function shared<T>() {
  const cache = new Map<string, Promise<T>>();
  return (key: string, load: () => Promise<T>) => {
    if (!cache.has(key)) cache.set(key, load().catch(error => { cache.delete(key); throw error; }));
    return cache.get(key)!;
  };
}
