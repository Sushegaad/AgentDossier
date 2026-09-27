"""FR-08: scoring profiles, normalization and unknown handling."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agentdossier.score import COMPONENTS, ScoringConfig, score, score_for_domain


@pytest.fixture(scope="module")
def cfg():
    return ScoringConfig.load()


def test_every_domain_has_a_profile(cfg):
    from agentdossier.util import load_config

    for domain in load_config("taxonomy.json")["domains"]:
        assert cfg.profile_for_domain(domain) in cfg.profiles


def test_perfect_components_score_100(cfg):
    raw = {c: cfg.seed_max[c] for c in COMPONENTS}
    for profile in cfg.profiles:
        assert score(raw, profile, cfg).score == 100.0


def test_unknown_component_scores_zero_and_is_flagged(cfg):
    raw = {c: cfg.seed_max[c] for c in COMPONENTS}
    raw["governance"] = None
    r = score(raw, "regulated", cfg)
    assert "governance" in r.unknown
    assert r.evidence_coverage == pytest.approx(85 / 100)
    assert r.score == pytest.approx(85.0)


def test_known_seed_row_reproduces(cfg):
    # Agentforce Financial Services, Finance & Banking #1: 96.9 in the workbook
    raw = {
        "adoption": 26,
        "trust": 25,
        "health": 20,
        "ecosystem": 15,
        "domain_fit": 99,
        "governance": 94,
        "docs": 10,
    }
    assert score_for_domain(raw, "finance", cfg).score == 96.9


@given(
    st.dictionaries(
        st.sampled_from(COMPONENTS), st.floats(min_value=0, max_value=100), min_size=7, max_size=7
    )
)
def test_score_is_bounded(raw):
    cfg = ScoringConfig.load()
    for profile in cfg.profiles:
        r = score(raw, profile, cfg)
        assert 0.0 <= r.score <= 100.0
        assert 0.0 <= r.evidence_coverage <= 1.0
