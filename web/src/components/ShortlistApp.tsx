import { useEffect, useState } from "react";
import { BASE, agentHref } from "../lib/data";
import { clearShortlist, getShortlist, onShortlistChange, toggleShortlist, type ShortlistItem } from "../lib/shortlist";

export default function ShortlistApp() {
  const [items, setItems] = useState<ShortlistItem[]>([]);
  useEffect(() => {
    setItems(getShortlist());
    return onShortlistChange(() => setItems(getShortlist()));
  }, []);

  const exportJson = () => {
    const blob = new Blob([JSON.stringify({ exported: new Date().toISOString(), items }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "agentdossier-shortlist.json";
    a.click();
    URL.revokeObjectURL(a.href);
  };

  if (items.length === 0)
    return (
      <p className="muted">
        Nothing shortlisted yet. Use the ☆ button on <a href={`${BASE}/`}>search results</a> or agent pages. The list is stored only in this
        browser.
      </p>
    );
  return (
    <div>
      <div className="row" style={{ marginBottom: "0.75rem" }}>
        <a className="btn primary" href={`${BASE}/compare/?ids=${items.slice(0, 4).map((i) => i.slug).join(",")}`}>
          Compare {Math.min(4, items.length)}
        </a>
        <button type="button" className="btn" onClick={exportJson}>
          Export JSON
        </button>
        <button type="button" className="btn" onClick={() => clearShortlist()}>
          Clear
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Agent</th>
            <th>Vendor</th>
            <th>Added</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {items.map((i) => (
            <tr key={i.id}>
              <td>
                <a href={agentHref(i.slug)}>{i.name}</a>
              </td>
              <td>{i.vendor}</td>
              <td className="muted small">{i.added.slice(0, 10)}</td>
              <td>
                <button type="button" className="btn small" onClick={() => toggleShortlist(i)}>
                  remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
