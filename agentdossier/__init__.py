"""AgentDossier: a standards-aware agent registry.

An evidence dossier for every AI agent. The core package (this module, util,
models, standards, connectors.seed_xlsx, score, classify, normalize, build)
uses only the Python standard library so the scanner installs with zero
dependencies. Server, connector and MCP features are optional extras.

Discovery is metadata-first and non-invasive: AgentDossier never executes a
third-party agent or tool. BRD reference: v3.2, 26 Sep 2026.
"""

__version__ = "1.0.0"
PARSER_VERSIONS = {"ard": "ard-0.91", "a2a": "a2a-0.3+1.0", "mcp": "mcp-2025-06-18"}
SCORE_VERSION = "sar-score-2.0"
