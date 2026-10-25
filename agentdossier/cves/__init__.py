"""The CVE registry: official CVEs related to AI agents, as a filterable list.

``nvd``    reads the official records (NVD API 2.0, which carries the CVE.org record plus CVSS and
           CPE) and the CISA KEV catalog; plans the backfill queries; replays saved responses offline.
``match``  decides what is agent-related (Test A: a listed product; Test B: an agent-specific
           weakness), assigns a category and surface tags — pure functions over records.
``build``  runs collect → match → overrides → link → write for ``agentdossier cves update``.

Rules (docs/cves.md): a row exists only because CVE.org has the ID; the description and scores are
the official record's own; nothing here is a scanner, a payload, or a score for an agent.
"""
