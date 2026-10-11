"""The sandbox harness: run an agent against a published prompt-injection benchmark and record
what it did as a trace.

"We urgently need more public traces of AI agents attacking and defending systems." Curated
reports and probe transcripts (:mod:`agentdossier.traces`) cover what already exists; the harness
*produces* new ones. It does not invent attack payloads — it runs the agent against
`AgentDojo <https://github.com/ethz-spylab/agentdojo>`_ (MIT), a peer-reviewed suite of injection
tasks and attacks, and records, per task, whether the injection succeeded, with the tool trace.
Every scenario is therefore public and citable, and a trace is reproducible by anyone with the
bundle and the model backend named in it.

AgentDojo measures a *model's* susceptibility inside a generic tool-use agent, so a harness trace
is ``scope: model``: inherited evidence for every catalog agent built on that model, shown as
model-level, never claimed as a test of one product. The mapping from a model to the agents it is
evidence for lives in ``data/traces/harness/models.yaml`` and is applied by
:func:`agentdossier.traces.apply_traces`.
"""

from __future__ import annotations

from .bundles import record_run
from .run import SOURCE, SOURCE_URL, SUITES, HarnessResult, run_suite

__all__ = ["SOURCE", "SOURCE_URL", "SUITES", "HarnessResult", "record_run", "run_suite"]
