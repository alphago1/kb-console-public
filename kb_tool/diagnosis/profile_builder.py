from __future__ import annotations

import json
from collections import defaultdict

from .schemas import DiagnosisSignal, UserKnowledgeProfile


def _merge_string_values(existing: str, incoming: str, incoming_conf: float) -> tuple[str, float]:
    if not existing:
        return incoming, incoming_conf
    if not incoming:
        return existing, 0.5
    if existing == incoming:
        return existing, min(1.0, incoming_conf + 0.15)
    if incoming_conf > 0.7:
        return incoming, incoming_conf
    return existing, 0.55


def _merge_list_values(existing: list, incoming: list, incoming_conf: float) -> tuple[list, float]:
    flat: list = []
    for item in list(existing or []) + list(incoming or []):
        if isinstance(item, (list, tuple)):
            flat.extend(item)
        else:
            flat.append(item)
    seen = set()
    combined: list = []
    for item in flat:
        if isinstance(item, dict):
            key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        else:
            key = str(item)
        if key not in seen:
            seen.add(key)
            combined.append(item)
    conf = min(1.0, incoming_conf + 0.15 * min(len(incoming), 5))
    return combined, conf


def _merge_dict_values(existing: dict, incoming: dict, incoming_conf: float) -> tuple[dict, float]:
    merged = {**(existing or {}), **(incoming or {})}
    return merged, incoming_conf


def build_profile(signals: list[DiagnosisSignal]) -> UserKnowledgeProfile:
    """Build a UserKnowledgeProfile from a list of DiagnosisSignals."""
    profile = UserKnowledgeProfile()
    field_values: dict[str, list[tuple[Any, float]]] = defaultdict(list)

    for sig in signals:
        if sig.inferred_value is None:
            continue
        field_values[sig.affects_decision].append((sig.inferred_value, sig.confidence))

    # Fields that expect list[dict] — convert string values
    _dict_list_fields = {"core_domains"}

    confidence_map: dict[str, float] = {}

    for field in profile.field_names():
        candidates: list[tuple[Any, float]] = [
            (v, c) for v, c in field_values.get(field, [])
        ]
        # also check signals keyed by affects_decision (fallback mapping)
        for sig in signals:
            if sig.inferred_value is None:
                continue
            if field == "primary_goal" and "目标" in str(sig.evidence_text)[:100]:
                candidates.append((sig.inferred_value, sig.confidence))

        if not candidates:
            confidence_map[field] = 0.0
            continue

        # Aggregate: pick highest-confidence value, merge lists
        vals_raw = [v for v, _ in candidates]
        best_conf = max(c for _, c in candidates)

        # Convert string values to dicts for dict-list fields
        if field in _dict_list_fields:
            flat: list = []
            for v in vals_raw:
                if isinstance(v, (list, tuple)):
                    flat.extend(v)
                else:
                    flat.append(v)
            vals = [
                {"name": v, "description": ""} if isinstance(v, str) else v
                for v in flat
            ]
        else:
            vals = vals_raw

        current = getattr(profile, field, None)
        if isinstance(current, list):
            merged, conf = _merge_list_values(current or [], vals, best_conf)
            setattr(profile, field, merged)
            confidence_map[field] = conf
        elif isinstance(current, dict):
            if all(isinstance(v, dict) for v in vals):
                merged_dict = {}
                for d in vals:
                    merged_dict.update(d)
                setattr(profile, field, merged_dict)
                confidence_map[field] = best_conf
            elif vals:
                setattr(profile, field, {"value": vals[0]} if len(vals) == 1 else {"values": vals})
                confidence_map[field] = best_conf
            else:
                confidence_map[field] = 0.0
        else:
            # string or scalar
            merged, conf = _merge_string_values(current or "", str(vals[0]), best_conf)
            setattr(profile, field, merged)
            confidence_map[field] = conf

    profile.confidence_map = confidence_map
    return profile


def update_profile(existing: UserKnowledgeProfile,
                   new_signals: list[DiagnosisSignal]) -> UserKnowledgeProfile:
    """Update an existing profile with new signals."""
    field_values: dict[str, list[tuple[Any, float]]] = defaultdict(list)
    for sig in new_signals:
        if sig.inferred_value is None:
            continue
        field_values[sig.affects_decision].append((sig.inferred_value, sig.confidence))

    confidence_map = dict(existing.confidence_map)

    for field in existing.field_names():
        candidates = field_values.get(field, [])
        if not candidates:
            continue

        vals = [v for v, _ in candidates]
        best_conf = max(c for _, c in candidates)
        current = getattr(existing, field, None)

        if isinstance(current, list):
            merged, conf = _merge_list_values(current or [], vals, best_conf)
            setattr(existing, field, merged)
            confidence_map[field] = max(confidence_map.get(field, 0.0), conf)
        elif isinstance(current, dict):
            for v in vals:
                if isinstance(v, dict):
                    current.update(v)
            setattr(existing, field, current)
            confidence_map[field] = max(confidence_map.get(field, 0.0), best_conf)
        else:
            merged, conf = _merge_string_values(current or "", str(vals[0]), best_conf)
            setattr(existing, field, merged)
            confidence_map[field] = max(confidence_map.get(field, 0.0), conf)

    existing.confidence_map = confidence_map
    return existing
