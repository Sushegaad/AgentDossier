"""The incident registry's weekly upkeep.

``scout``   reads a curated list of public feeds (config/trace_sources.json), keeps the items that look
            like an AI agent attacking, defending or being exploited, and records them as *candidates*
            in data/curated/incident_candidates.yaml. A candidate is a lead — title, link, date, outlet,
            snippet — never an incident: a person promotes it (``incidents draft``) and completes the
            record before it is published. Nothing here writes an incident.
``recheck`` re-fetches every published incident's sources and records which are still reachable
            (data/curated/incident_source_check.json), so "as reported" stays checkable over time.

Both run in the weekly refresh workflow and ship in its pull request.
"""
