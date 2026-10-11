// Display labels derived from the repository configuration (single source of truth).
import taxonomy from "../../../config/taxonomy.json";
import type { Tier } from "./types";

type FrameworkFile = { id: string; name: string; group: string; jurisdictions: string[]; variants: string[] };
const frameworkFiles = import.meta.glob<FrameworkFile>("../../../config/frameworks/*.json", {
  eager: true,
  import: "default",
});

export const FRAMEWORKS: Record<string, FrameworkFile> = Object.fromEntries(
  Object.values(frameworkFiles).map((f) => [f.id, f]),
);

export const SHORT_NAMES: Record<string, string> = {
  c5: "BSI C5",
  csa_star: "CSA STAR",
  cyber_essentials: "Cyber Essentials",
  dora: "DORA",
  eu_ai_act: "EU AI Act",
  fedramp: "FedRAMP",
  gdpr: "GDPR",
  govramp: "GovRAMP",
  hipaa: "HIPAA",
  hitrust: "HITRUST",
  irap: "IRAP",
  iso27001: "ISO 27001",
  iso27701: "ISO 27701",
  iso42001: "ISO 42001",
  nist_ai_rmf: "NIST AI RMF",
  pci_dss: "PCI DSS",
  soc2: "SOC 2",
  uk_gdpr: "UK GDPR",
  uk_us_data_bridge: "UK-US Data Bridge",
};

export function frameworkName(id: string, short = true): string {
  return (short && SHORT_NAMES[id]) || FRAMEWORKS[id]?.name || id;
}

export function variantLabel(variant: string | null | undefined): string {
  if (!variant) return "";
  return variant
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace("Soc2", "SOC 2")
    .replace("Type Ii", "Type II")
    .replace(/\bIso(\d)/, "ISO $1")
    .replace("Fedramp", "FedRAMP")
    .replace("Li Saas", "LI-SaaS")
    .replace("20x", "20x")
    .replace("Dpf", "DPF")
    .replace("Dpa", "DPA")
    .replace("Baa", "BAA")
    .replace("Sccs", "SCCs")
    .replace("Eu ", "EU ")
    .replace("Uk ", "UK ")
    .replace("Hitrust", "HITRUST")
    .replace("Gpai", "GPAI")
    .replace("Art42", "Art. 42")
    .replace("Art50", "Art. 50")
    .replace("Star For Ai", "STAR for AI")
    .replace("Star Level", "STAR Level")
    .replace("Aiuc 1", "AIUC-1")
    .replace("Nist Ai Rmf", "NIST AI RMF")
    .replace("Nist Csf 2", "NIST CSF 2.0")
    .replace("Pci Dss", "PCI DSS")
    .replace(/\b(Available|Active|Aligned|Statement|Claimed|Registered|Signatory|Residency)\b/g, (w) =>
      w.toLowerCase(),
    )
    .replace("Idta Or Addendum", "IDTA or Addendum")
    .replace("Service Provider L", "Service Provider Level ");
}

export const TIER_LABEL: Record<Tier, string> = {
  1: "Registry-matched",
  2: "Marketplace-listed",
  3: "Document-evidenced",
  4: "Vendor-claimed",
  5: "Unknown",
};

export const TIER_SHORT: Record<Tier, string> = {
  1: "T1",
  2: "T2",
  3: "T3",
  4: "T4",
  5: "T5",
};

export const IDENTITY_LABEL: Record<Tier, string> = {
  1: "ARD manifest bound to publisher domain",
  2: "Vendor-domain page, marketplace listing or metadata at publisher domain",
  3: "Repository ownership or inferred publisher domain",
  4: "Vendor name only",
  5: "Unknown",
};

/** One word per identity tier for the site; the T-scale is reserved for compliance evidence. */
export const IDENTITY_WORD: Record<Tier, string> = { 1: "confirmed", 2: "confirmed", 3: "likely", 4: "unconfirmed", 5: "unknown" };

/** The protocol tier (1 verified · 3 claimed · 5 none) as a word. */
export const PROTOCOL_TIER_WORD: Record<number, string> = { 1: "verified", 3: "documented", 5: "none found" };

/** NVD result as a sentence; it is a keyword search, never a tier. */
export function securityWord(sec: { cves?: number | null } | null | undefined, tier?: number | null): string {
  if (sec && sec.cves != null) return sec.cves === 0 ? "NVD: no CVE by keyword" : `NVD: ${sec.cves} CVE${sec.cves === 1 ? "" : "s"} by keyword`;
  return tier ? "NVD: checked" : "NVD: not checked";
}

export const IDENTITY_EVIDENCE: Record<string, string> = {
  ard_trust_manifest_binding: "ARD trust manifest binds the publisher domain",
  marketplace_listing: "listed on a cloud marketplace under the vendor's account",
  standards_metadata_at_publisher_domain: "ARD or A2A metadata served at the publisher's own domain",
  maintainer_verified_publisher_domain: "publisher domain confirmed by the maintainer",
  vendor_domain_product_page: "product page served from the vendor's own domain",
  repository_ownership: "repository or Hub account ownership",
  publisher_domain_matches_vendor: "resource URL on a domain that carries the vendor's name",
  vendor_name_only: "only the vendor name is known",
};

export const DOMAINS: Record<string, { label: string; keywords?: string[]; profile?: string }> = taxonomy.domains as never;

export function domainLabel(id: string): string {
  return DOMAINS[id]?.label ?? id;
}

export const SOURCE_LABEL: Record<string, string> = {
  fedramp: "FedRAMP Marketplace",
  csa_star: "CSA STAR Registry",
  dpf: "dataprivacyframework.gov",
  iaf_certsearch: "IAF CertSearch",
  aws_marketplace: "AWS Marketplace",
  microsoft_agent_store: "Microsoft Agent Store",
  google_cloud_marketplace: "Google Cloud Marketplace",
  vendor_trust_centers: "vendor page",
  curated: "maintainer review",
  seed_xlsx: "seed workbook",
  github: "GitHub",
  huggingface: "Hugging Face",
  mcp_registry: "MCP Registry",
  ard_web: "ARD publisher",
  nvd: "NVD",
};

export function sourceLabel(id: string | undefined | null): string {
  return (id && SOURCE_LABEL[id]) || id || "";
}

export const NEWS_TAG_LABEL: Record<string, string> = {
  security_incident: "Security incident",
  outage: "Outage",
  legal_regulatory: "Legal / regulatory",
  funding: "Funding",
  pricing: "Pricing",
  partnership: "Partnership",
  launch: "Launch",
  product_update: "Product update",
  review: "Review",
  opinion: "Opinion",
  news: "News",
  cve: "CVE",
};

export const RISK_TAGS = new Set(["security_incident", "outage", "legal_regulatory", "cve"]);

export function protocolLabel(status: string): string {
  return { verified: "Verified", claimed: "Claimed", unknown: "Not checked", failed: "Failed" }[status] ?? status;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  return iso.slice(0, 10);
}

/** Short badge text: "SOC 2 Type II", "STAR Level 2", "ISO 27017", "FedRAMP Moderate", "HIPAA BAA available". */
export function badgeLabel(framework: string, variant: string | null | undefined): string {
  const fw = frameworkName(framework);
  if (!variant) return fw;
  const v = variantLabel(variant);
  if (v.startsWith(fw) || /^(ISO|STAR|AIUC|FedRAMP|Cyber Essentials|HITRUST|NIST|PCI DSS)/.test(v)) return v;
  return `${fw} ${v}`;
}
