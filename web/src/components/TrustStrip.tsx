import type { TrustSummary } from "../lib/types";
import { IDENTITY_WORD, PROTOCOL_TIER_WORD } from "../lib/labels";

type StripKey = Exclude<keyof TrustSummary, "vendor_compliance">;

const LABELS: Record<StripKey, string> = {
  identity: "Publisher",
  compliance: "Evidence",
  security: "Security",
  protocols: "Protocols",
  issues: "Issues",
};

const TITLES: Record<StripKey, (t: number | null) => string> = {
  identity: (t) =>
    ({ 1: "ARD manifest bound to publisher domain", 2: "Marketplace listing or metadata at publisher domain", 3: "Repository ownership or publisher domain", 4: "Vendor name only", 5: "Identity unknown" })[t ?? 5] ?? "",
  compliance: (t) =>
    ({ 1: "Best evidence: registry-matched", 2: "Best evidence: marketplace-listed", 3: "Best evidence: document-evidenced", 4: "Best evidence: vendor-claimed", 5: "No compliance evidence found" })[t ?? 5] ?? "",
  security: (t) => (t == null ? "Security not checked" : "NVD keyword search done; see the dossier for what it matched"),
  protocols: (t) => ({ 1: "A2A/MCP/ARD verified", 3: "Protocol support claimed", 5: "No protocol metadata observed" })[t ?? 5] ?? "",
  issues: (t) => (t == null ? "Issues not checked" : t === 1 ? "No open issues found" : "Open issues: see profile"),
};

export default function TrustStrip({ trust, compact = false }: { trust: TrustSummary; compact?: boolean }) {
  const keys = Object.keys(LABELS) as StripKey[];
  return (
    <div className="trust-strip" aria-label="Trust summary">
      {keys.map((k) => {
        const t = trust[k] ?? null;
        const label = t == null ? "–" : k === "identity" ? IDENTITY_WORD[t as 1 | 2 | 3 | 4 | 5] : k === "security" ? "keyword" : k === "protocols" ? (PROTOCOL_TIER_WORD[t] ?? `T${t}`) : k === "issues" ? (t === 1 ? "none" : "linked") : `T${t}`;
        return (
          <span key={k} className="tierbox" title={TITLES[k](t)}>
            {compact ? "" : `${LABELS[k]} `}
            {label}
          </span>
        );
      })}
    </div>
  );
}
