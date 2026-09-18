"""성분 충돌 검수 — YAML 규칙만 본다. LLM 없음.

pair의 양쪽이 (사용 중 성분 ∪ 후보 actives)에 있고, 그중 하나 이상이 후보 쪽이면
규칙을 적용한다. caution은 남기고, avoid는 그 후보를 뺀다.
"""

from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import BASE_DIR
from app.graph.state import CurationState, append_trace

RULES_PATH = BASE_DIR / "data" / "conflict_rules.yaml"

# 화면 칩 / 자유 입력 → 규칙 키. AHA/BHA는 두 키로 펼친다.
ACTIVE_ALIASES: dict[str, list[str]] = {
    "retinol": ["retinol"],
    "레티놀": ["retinol"],
    "aha": ["aha"],
    "aha/bha": ["aha", "bha"],
    "bha": ["bha"],
    "vitamin_c": ["vitamin_c"],
    "비타민c": ["vitamin_c"],
    "비타민 c": ["vitamin_c"],
    "niacinamide": ["niacinamide"],
    "나이아신아마이드": ["niacinamide"],
    "나이아신": ["niacinamide"],
    "benzoyl_peroxide": ["benzoyl_peroxide"],
    "벤조일퍼옥사이드": ["benzoyl_peroxide"],
}


@lru_cache
def load_rules(path: Path = RULES_PATH) -> tuple[dict[str, str], list[dict[str, Any]]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    labels: dict[str, str] = raw.get("labels") or {}
    rules: list[dict[str, Any]] = raw.get("rules") or []
    return labels, rules


def normalize_actives(raw: list[str]) -> set[str]:
    keys: set[str] = set()
    for item in raw:
        token = " ".join(item.strip().lower().split())
        if not token:
            continue
        mapped = ACTIVE_ALIASES.get(token) or ACTIVE_ALIASES.get(item.strip())
        if mapped:
            keys.update(mapped)
        else:
            keys.add(token)
    return keys


def _matches(rule: dict[str, Any], universe: set[str], product_keys: set[str]) -> bool:
    pair = set(rule["pair"])
    if not pair <= universe:
        return False
    return bool(pair & product_keys)


def _to_caution(rule: dict[str, Any], labels: dict[str, str]) -> dict[str, Any]:
    pair: list[str] = list(rule["pair"])
    return {
        "pair": pair,
        "pair_labels": [labels.get(k, k) for k in pair],
        "severity": rule["severity"],
        "message": rule["message"],
        "source": rule["source"],
        "confidence": rule["confidence"],
    }


async def conflict_checker(state: CurationState) -> dict[str, Any]:
    started = time.perf_counter()
    labels, rules = load_rules()
    user_keys = normalize_actives(state["profile"].get("current_actives") or [])

    kept: list[dict[str, Any]] = []
    cautions_by_id: dict[str, dict[str, Any]] = {}

    for candidate in state.get("candidates") or []:
        product_keys = set(candidate.get("actives") or [])
        universe = user_keys | product_keys
        drop = False
        for rule in rules:
            if not _matches(rule, universe, product_keys):
                continue
            cautions_by_id[rule["id"]] = _to_caution(rule, labels)
            if rule["severity"] == "avoid":
                drop = True
        if not drop:
            kept.append(candidate)

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "candidates": kept,
        "cautions": list(cautions_by_id.values()),
        "trace": append_trace(
            state,
            "conflict_checker",
            elapsed_ms,
            kept=len(kept),
            caution_count=len(cautions_by_id),
        ),
    }
