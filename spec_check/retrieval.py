"""Deterministic BM25 baseline with datasheet synonyms and document balancing."""
import math
import re
from collections import Counter
from .store import connect

STOP = set("the a an is are of for in on what which how can be this these to and or with it its does do at from me tell please".split())
SYNONYMS = [
    {"supply", "voltage", "vcc", "vdd", "vm", "operating"},
    {"maximum", "max", "limit", "limits"}, {"minimum", "min"},
    {"pin", "pins", "pinout", "terminal", "terminals"},
    {"thermal", "temperature", "junction"},
    {"current", "amp", "amps", "amperes"},
    {"stall", "locked", "rotor"},
]


def tokenize(text):
    return [t for t in re.findall(r"[a-z]+[a-z0-9]*|\d+(?:\.\d+)?", text.lower()) if t not in STOP]


def search(question, document_ids, limit=12):
    if not document_ids:
        return []
    with connect() as db:
        rows = [dict(r) for r in db.execute(
            f"SELECT c.*, d.name FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.id IN ({','.join('?' for _ in document_ids)})",
            document_ids,
        )]
    return rank_chunks(question, rows, document_ids, limit)


def rank_chunks(question, rows, document_ids, limit=12):
    """Use the same retrieval algorithm for SQLite and browser-owned corpora."""
    if not rows or not document_ids:
        return []
    original = set(tokenize(question))
    if not original:
        return []
    terms = {t: 1.0 for t in original}
    for group in SYNONYMS:
        if original & group:
            for term in group - original:
                terms[term] = 0.35
    counts = [Counter(tokenize(row["text"])) for row in rows]
    lengths = [sum(c.values()) for c in counts]
    avg = sum(lengths) / max(len(rows), 1) or 1
    frequency = Counter(t for count in counts for t in count)
    scored = []
    for row, count, length in zip(rows, counts, lengths):
        # Require a real query term; synonyms alone must not fabricate relevance.
        if not original.intersection(count):
            continue
        score = 0
        for term, weight in terms.items():
            tf = count[term]
            idf = math.log(1 + (len(rows) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            score += weight * idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / avg))
        # Revision logs and contents pages repeat specification words without giving
        # the actual ratings. Keep them searchable but prioritize substantive pages.
        lower = row["text"].lower()
        if "revision history" in lower or "changes from revision" in lower or lower.count(".....") > 4:
            score *= 0.4
        if row["kind"] == "table":
            score *= 1.1
        row["score"] = round(score, 4)
        scored.append(row)
    scored.sort(key=lambda r: (-r["score"], r["id"]))
    # Reserve evidence for each selected part before filling the remaining slots.
    selected = []
    quota = max(1, limit // len(document_ids))
    for doc_id in document_ids:
        selected.extend([r for r in scored if r["document_id"] == doc_id][:quota])
    used = {r["id"] for r in selected}
    selected.extend(r for r in scored if r["id"] not in used)
    return selected[:limit]
