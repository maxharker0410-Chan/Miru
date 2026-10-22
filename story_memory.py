"""Character-scoped recall and witnessed history, without extra model calls."""
from __future__ import annotations

import re


def _terms(text):
    text = text.casefold()
    terms = set(re.findall(r"[a-z0-9_]{2,}", text))
    for part in re.findall(r"[\u3400-\u9fff]+", text):
        terms.update(part[i:i + 2] for i in range(len(part) - 1))
    return terms


def remember(session, character_id, values):
    """Keep the full personal record; bound retrieval rather than deleting facts."""
    if not isinstance(values, list):
        return
    memories = session["memories"][character_id]
    for value in values[:2]:
        if isinstance(value, str):
            value = value.strip()[:240]
            if value and value not in memories:
                memories.append(value)


def recall(session, character_id, query, limit=20):
    """Reserve recent context and retrieve older, relevant personal experiences."""
    values = session.get("memories", {}).get(character_id, [])
    values = list(dict.fromkeys(v.strip()[:240] for v in values
                               if isinstance(v, str) and v.strip()))
    if len(values) <= limit:
        return values
    recent_count = min(12, limit)
    cutoff = len(values) - recent_count
    query_terms = _terms(query)
    ranked = [(len(query_terms & _terms(value)), index)
              for index, value in enumerate(values[:cutoff])]
    relevant = sorted((item for item in ranked if item[0]), reverse=True)
    selected = {index for _, index in relevant[:limit - recent_count]}
    selected.update(range(cutoff, len(values)))
    # When no older experience matches, retain the ordinary recent context.
    for index in range(cutoff - 1, -1, -1):
        if len(selected) >= limit:
            break
        selected.add(index)
    return [values[index] for index in sorted(selected)]


def witnessed_history(messages, character_id, limit=20):
    """An old untagged transcript cannot establish that a character was there."""
    return [message for message in messages
            if character_id in message.get("witness_ids", [])
            or message.get("speaker") == character_id][-limit:]
