// Browser-local shortlist (FR-33): nothing leaves the browser.
export interface ShortlistItem {
  id: string;
  slug: string;
  name: string;
  vendor: string | null;
  added: string;
}
const KEY = "agentdossier.shortlist.v1";
const EVENT = "agentdossier:shortlist";

export function getShortlist(): ShortlistItem[] {
  try {
    const raw = typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null;
    return raw ? (JSON.parse(raw) as ShortlistItem[]) : [];
  } catch {
    return [];
  }
}

function save(items: ShortlistItem[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(items));
  } catch {
    /* private mode or storage disabled: shortlist is per page load only */
  }
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(EVENT));
}

export function inShortlist(id: string): boolean {
  return getShortlist().some((i) => i.id === id);
}

export function toggleShortlist(item: Omit<ShortlistItem, "added">): boolean {
  const items = getShortlist();
  const idx = items.findIndex((i) => i.id === item.id);
  if (idx >= 0) {
    items.splice(idx, 1);
    save(items);
    return false;
  }
  items.push({ ...item, added: new Date().toISOString() });
  save(items);
  return true;
}

export function clearShortlist() {
  save([]);
}

export function onShortlistChange(fn: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(EVENT, fn);
  window.addEventListener("storage", fn);
  return () => {
    window.removeEventListener(EVENT, fn);
    window.removeEventListener("storage", fn);
  };
}
