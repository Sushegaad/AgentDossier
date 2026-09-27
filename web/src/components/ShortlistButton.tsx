import { useEffect, useState } from "react";
import { inShortlist, onShortlistChange, toggleShortlist } from "../lib/shortlist";

export default function ShortlistButton({
  id,
  slug,
  name,
  vendor,
  small = false,
}: {
  id: string;
  slug: string;
  name: string;
  vendor: string | null;
  small?: boolean;
}) {
  const [on, setOn] = useState(false);
  useEffect(() => {
    setOn(inShortlist(id));
    return onShortlistChange(() => setOn(inShortlist(id)));
  }, [id]);
  return (
    <button
      type="button"
      className={`btn${small ? " small" : ""}`}
      aria-pressed={on}
      onClick={() => setOn(toggleShortlist({ id, slug, name, vendor }))}
      title={on ? "Remove from shortlist" : "Add to shortlist (stored in this browser only)"}
    >
      {on ? "★ Shortlisted" : "☆ Shortlist"}
    </button>
  );
}
