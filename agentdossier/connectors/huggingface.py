"""Hugging Face Hub connector (FR-01): Spaces and models tagged as agents.

Public metadata only (``/api/spaces``, ``/api/models``). Likes, tags, SDK
and dates are recorded as signals; nothing is downloaded or executed.
"""

from __future__ import annotations

from typing import Any

from ..models import new_resource
from ..util import NetPolicy
from .base import ConnectorReport, SnapshotStore, get_json

API = "https://huggingface.co/api"
SOURCE = "huggingface"
SPACE_QUERIES = ("agent", "mcp", "a2a", "agentic")
MODEL_FILTERS = ("agent",)


def space_to_resource(space: dict[str, Any], payload_hash: str | None = None) -> dict[str, Any]:
    sid = space["id"]
    card = space.get("cardData") or {}
    name = card.get("title") or sid.split("/")[-1]
    res = new_resource(
        name=name,
        source_system=SOURCE,
        source_url=f"https://huggingface.co/spaces/{sid}",
        vendor=space.get("author") or sid.split("/")[0],
        url=f"https://huggingface.co/spaces/{sid}",
        resource_type="agent",
        category="Hugging Face Space",
        description=card.get("short_description") or None,
        external_ids={"huggingface_space": sid},
        raw=space,
        key=f"hf:space:{sid.lower()}",
    )
    res["license"] = card.get("license")
    res["commercial"] = False
    res["tags"] = sorted({t for t in space.get("tags") or [] if not t.startswith("region:")})[:30]
    res["deployment"] = "hosted"
    res["signals"] = {
        "hf_likes": space.get("likes"),
        "hf_sdk": space.get("sdk"),
        "hf_last_modified": space.get("lastModified"),
        "hf_created_at": space.get("createdAt"),
        "hf_pinned": bool(card.get("pinned")),
    }
    if payload_hash:
        res["sources"][0]["payload_hash"] = payload_hash
    return res


def model_to_resource(model: dict[str, Any], payload_hash: str | None = None) -> dict[str, Any]:
    mid = model.get("modelId") or model["id"]
    res = new_resource(
        name=mid.split("/")[-1],
        source_system=SOURCE,
        source_url=f"https://huggingface.co/{mid}",
        vendor=model.get("author") or mid.split("/")[0],
        url=f"https://huggingface.co/{mid}",
        resource_type="framework",
        category="Hugging Face model (agent)",
        description=None,
        external_ids={"huggingface_model": mid},
        raw=model,
        key=f"hf:model:{mid.lower()}",
    )
    res["tags"] = sorted({t for t in model.get("tags") or [] if ":" not in t})[:30]
    res["commercial"] = False
    res["signals"] = {
        "hf_likes": model.get("likes"),
        "hf_downloads": model.get("downloads"),
        "hf_last_modified": model.get("lastModified"),
        "hf_pipeline": model.get("pipeline_tag"),
        "hf_library": model.get("library_name"),
    }
    if payload_hash:
        res["sources"][0]["payload_hash"] = payload_hash
    return res


def run(
    *,
    store: SnapshotStore | None,
    limit: int = 500,
    min_likes: int = 5,
    policy: NetPolicy | None = None,
    include_models: bool = True,
) -> tuple[list[dict[str, Any]], ConnectorReport]:
    report = ConnectorReport(SOURCE)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for q in SPACE_QUERIES:
        url = f"{API}/spaces?search={q}&sort=likes&direction=-1&limit={limit}&full=true"
        data, r, h = get_json(store, SOURCE, f"spaces:{q}", url, policy=policy)
        report.fetched += 1
        if not isinstance(data, list):
            report.error(f"{url}: {r.error if r else 'no data'}")
            continue
        for space in data:
            if space.get("private") or (space.get("likes") or 0) < min_likes or space["id"] in seen:
                report.skipped += 1
                continue
            seen.add(space["id"])
            out.append(space_to_resource(space, h))
    if include_models:
        for f in MODEL_FILTERS:
            url = f"{API}/models?filter={f}&sort=likes&direction=-1&limit={limit}&full=true"
            data, r, h = get_json(store, SOURCE, f"models:{f}", url, policy=policy)
            report.fetched += 1
            if not isinstance(data, list):
                report.error(f"{url}: {r.error if r else 'no data'}")
                continue
            for model in data:
                mid = model.get("modelId") or model.get("id")
                if (
                    not mid
                    or model.get("private")
                    or model.get("gated")
                    or (model.get("likes") or 0) < min_likes
                    or mid in seen
                ):
                    report.skipped += 1
                    continue
                seen.add(mid)
                out.append(model_to_resource(model, h))
    report.produced = len(out)
    return out, report
