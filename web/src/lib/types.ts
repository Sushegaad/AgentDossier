// Shapes of the catalog files written by `agentdossier build` (schema/*.schema.json).

export type Tier = 1 | 2 | 3 | 4 | 5;
export type ProtocolStatus = "verified" | "claimed" | "unknown" | "failed";

export interface TrustSummary {
  identity: Tier;
  compliance: Tier;
  /** best vendor-level (inherited) tier, null when none */
  vendor_compliance?: Tier | null;
  security: Tier | null;
  protocols: Tier;
  issues: Tier | null;
}

export interface ComplianceSummary {
  framework: string;
  variant: string | null;
  tier: Tier;
  status: string;
  credited?: boolean;
  source?: string;
}

export interface IndexRecord {
  id: string;
  slug: string;
  name: string;
  vendor: string | null;
  resource_type: string;
  category: string | null;
  license: string | null;
  deployment: string | null;
  scope: "public" | "private";
  domains: Record<string, { rank: number | null; score: number | null }>;
  trust: TrustSummary;
  protocols: Record<string, ProtocolStatus>;
  compliance_summary: ComplianceSummary[];
  sources: string[];
  description: string | null;
  tags: string[];
}

export interface CatalogIndex {
  snapshot_date: string;
  built_at: string;
  score_version: string;
  taxonomy_version?: string;
  frameworks_version?: string;
  scope: "public" | "private";
  tenant: string | null;
  disclaimer: string;
  generator?: string;
  records: IndexRecord[];
}

export interface SearchDoc {
  id: string;
  slug: string;
  name: string;
  vendor: string;
  description: string;
  tags: string;
  capabilities: string;
  queries: string;
  category: string;
  domains: string;
}

export interface ComplianceRecord extends ComplianceSummary {
  scope: string;
  covers_resource: string;
  issuer: string | null;
  certificate_id: string | null;
  issued: string | null;
  valid_until: string | null;
  period_end: string | null;
  evidence_url: string;
  retrieved_at: string;
  payload_hash: string | null;
  match_confidence: number | null;
  reviewer: string | null;
  review_reason: string | null;
  next_check: string | null;
  display: string;
  stale_since?: string;
  detail?: Record<string, unknown>;
}

export interface NewsItem {
  headline: string;
  url: string;
  outlet: string;
  date: string;
  tag: string;
  summary: string | null;
  kind: string;
  link_confidence: number;
  cluster_size?: number;
  discussion_url?: string;
  engagement?: number;
}

export interface IssueLink {
  kind: string;
  url: string;
  date: string;
  title: string;
}

export interface Issues {
  regulator_actions: number;
  cves: number;
  advisories: number;
  incidents: number;
  withdrawn_certificates: number;
  links: IssueLink[];
}

export interface DomainEntry {
  rank: number | null;
  score: number | null;
  recomputed?: number | null;
  profile?: string;
  confidence?: number;
  evidence_coverage?: number;
  score_version?: string;
  source?: string;
  seed_rank?: number | null;
  seed_score?: number | null;
  governance_credited?: Record<string, number>;
  components?: Record<string, number | null>;
}

export interface ProtocolBlock {
  status: ProtocolStatus;
  checked_at?: string | null;
  card_url?: string | null;
  manifest_url?: string | null;
  endpoint?: string | null;
  version?: string | null;
  transport?: string | null;
  tools?: number | null;
  error?: string | null;
  trust_manifest?: string | null;
  [k: string]: unknown;
}

export interface Resource {
  id: string;
  slug: string;
  name: string;
  vendor: string | null;
  url: string | null;
  canonical_url?: string | null;
  publisher_domain?: string | null;
  resource_type: string;
  category: string | null;
  license: string | null;
  commercial?: boolean | null;
  deployment: string | null;
  description: string | null;
  tags?: string[];
  capabilities?: string[];
  scope: "public" | "private";
  tenant?: string | null;
  domains: Record<string, DomainEntry>;
  components?: Record<string, number | null>;
  trust: TrustSummary;
  identity: { tier: Tier; evidence: string[]; rules_version: string; verified_by?: string; verified_on?: string };
  protocols: Record<string, ProtocolBlock>;
  compliance: ComplianceRecord[];
  security?: { tier: Tier; cves: number; advisories: number; checked_at: string; source?: string } | null;
  issues?: Issues;
  news?: NewsItem[];
  news_checked?: boolean;
  sources: { system: string; url?: string | null; payload_hash?: string | null; retrieved_at?: string }[];
  external_ids?: Record<string, string>;
  signals?: Record<string, unknown>;
  first_seen?: string;
  last_seen?: string;
  disclaimer?: string;
  governance?: Record<string, unknown>;
  merged_ids?: string[];
}

export interface DomainFile {
  domain: string;
  label: string;
  snapshot_date: string;
  built_at?: string;
  score_version: string;
  profile: string;
  ranked: (Pick<IndexRecord, "id" | "slug" | "name" | "vendor" | "category" | "resource_type" | "license" | "trust" | "protocols"> & {
    rank: number;
    score: number;
    profile: string;
    evidence_coverage: number;
    components: Record<string, number | null>;
    confidence: number;
  })[];
  discovered: IndexRecord[];
  disclaimer: string;
  note?: string;
}

export interface ChangelogEvent {
  at: string;
  resource_id: string;
  resource: string;
  event: "badge_added" | "badge_changed" | "badge_removed";
  framework: string;
  variant: string | null;
  tier?: Tier;
  status?: string;
  source?: string;
  from?: { tier?: Tier; status?: string };
  to?: { tier?: Tier; status?: string };
}
