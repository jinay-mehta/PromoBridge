from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .config import HIGH_SCORE_THRESHOLD, LOW_SCORE_THRESHOLD, MIN_TOP_TWO_MARGIN, MIN_MEANINGFUL_TOKENS

STOPWORDS = set("a an the and or but if then than to of in on at by for from with as is are was were be been being it its this that these those i you he she they we my your his her their our me him them us do does did can could would should will shall may might must not no yes so very just there here what when where why how who which while because into about after before over under again more most some any all have has had having get got gets am im its youre theyre dont didnt cant wont isnt arent wasnt werent".split())


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if value != value:  # NaN
            return ""
    except Exception:
        pass
    return str(value)


def normalize(text: str) -> str:
    text = _as_text(text).lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def meaningful_tokens(text: str) -> list[str]:
    return [t for t in normalize(text).split() if t not in STOPWORDS and len(t) > 1]


def _safe_cosine(query: str, docs: list[str], analyzer: str, ngram_range: tuple[int, int]) -> list[float]:
    if not docs or not normalize(query):
        return [0.0] * len(docs)
    try:
        vectorizer = TfidfVectorizer(analyzer=analyzer, ngram_range=ngram_range, sublinear_tf=True)
        matrix = vectorizer.fit_transform(docs + [query])
        sims = cosine_similarity(matrix[-1], matrix[:-1]).ravel().tolist()
        return [float(max(0.0, min(1.0, x))) for x in sims]
    except ValueError:
        return [0.0] * len(docs)


def text_similarity(query: str, docs: list[str], exact_query: str | None = None) -> list[dict[str, float]]:
    word = _safe_cosine(query, docs, "word", (1, 2))
    char = _safe_cosine(query, docs, "char_wb", (3, 5))
    q_tokens = set(meaningful_tokens(query))
    rows = []
    nq = normalize(query)
    nq_exact = normalize(exact_query) if exact_query is not None else nq
    for i, doc in enumerate(docs):
        d_tokens = set(meaningful_tokens(doc))
        overlap = len(q_tokens & d_tokens) / max(1, len(q_tokens))
        partial = fuzz.token_set_ratio(nq, normalize(doc)) / 100.0 if nq else 0.0
        exact = 1.0 if nq_exact and nq_exact in normalize(doc) else 0.0
        # Weighted, deterministic baseline. Not a calibrated probability.
        score = (0.20 * word[i] + 0.14 * char[i] + 0.22 * overlap + 0.10 * partial + 0.34 * exact)
        rows.append({"word_tfidf": word[i], "char_tfidf": char[i], "token_overlap": overlap,
                     "fuzzy": partial, "exact_phrase": exact, "content_score": float(score)})
    return rows


def title_similarity(displayed_title: str, show_title: str, aliases: list[str], episode_title: str) -> float:
    q = normalize(displayed_title)
    if not q:
        return 0.0
    alias_list = aliases if isinstance(aliases, list) else ([x.strip() for x in aliases.split(",") if x.strip()] if isinstance(aliases, str) else [])
    candidates = [show_title, episode_title] + alias_list
    scores = [fuzz.token_set_ratio(q, normalize(x)) / 100.0 for x in candidates if normalize(x)]
    return max(scores, default=0.0)


def score_candidates(promo: dict[str, Any], episodes: list[dict[str, Any]], top_k: int = 5,
                     use_semantic: bool = False, semantic_model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> list[dict[str, Any]]:
    query_parts = [_as_text(promo.get("transcript_raw", "")), _as_text(promo.get("caption", ""))]
    query = " ".join(x for x in query_parts if x).strip()
    spans = []
    for ep in episodes:
        for ev in ep.get("evidence", []):
            spans.append((ep, ev))
    docs = [str(ev.get("text", "")) for _, ev in spans]
    exact_query = _as_text(promo.get("transcript_raw", ""))
    sim_rows = text_similarity(query, docs, exact_query=exact_query)
    semantic_rows = None
    if use_semantic:
        from .semantic import semantic_similarities
        semantic_rows = semantic_similarities(query, docs, semantic_model_name)
        for idx, sim in enumerate(sim_rows):
            semantic_score = semantic_rows[idx]
            # Semantic retrieval helps paraphrases, while the lexical exact-evidence signal remains visible.
            sim["semantic_score"] = semantic_score
            sim["content_score"] = 0.70 * sim["content_score"] + 0.30 * semantic_score

    episode_rows: dict[str, dict[str, Any]] = {}
    for (ep, ev), sim in zip(spans, sim_rows):
        ep_id = ep["episode_id"]
        title_score = title_similarity(promo.get("displayed_title", ""), ep.get("canonical_title", ""),
                                        ep.get("aliases", []), ep.get("episode_title", ""))
        has_title = bool(normalize(promo.get("displayed_title", "")))
        total = (0.90 * sim["content_score"] + 0.10 * title_score) if has_title else sim["content_score"]
        record = {
            "show_id": ep["show_id"], "canonical_title": ep["canonical_title"],
            "episode_id": ep_id, "episode_number": ep.get("episode_number"),
            "episode_title": ep.get("episode_title", ""), "language": ep.get("language", "Unknown"),
            "territory": ep.get("territory", "Unknown"), "release_status": ep.get("release_status", "Unknown"),
            "destination_url": ep.get("destination_url", ""),
            "score": float(total), "content_score": sim["content_score"], "title_score": title_score,
            "component_scores": sim, "evidence": ev, "retrieval_mode": "hybrid-semantic" if use_semantic else "lexical-baseline",
        }
        if ep_id not in episode_rows or total > episode_rows[ep_id]["score"]:
            episode_rows[ep_id] = record

    ranked = sorted(episode_rows.values(), key=lambda x: x["score"], reverse=True)
    return ranked[:top_k]


def decide_status(promo: dict[str, Any], candidates: list[dict[str, Any]], metadata_errors: list[str] | None = None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if metadata_errors:
        return "METADATA ERROR", list(metadata_errors)
    text = " ".join([_as_text(promo.get("transcript_raw", "")), _as_text(promo.get("caption", ""))]).strip()
    tokens = meaningful_tokens(text)
    if len(tokens) < MIN_MEANINGFUL_TOKENS:
        return "NEEDS REVIEW", ["Very little distinctive text was supplied; add more dialogue or a caption."]
    if not candidates:
        return "NO MATCH", ["No screenplay evidence could be retrieved."]
    top = candidates[0]
    second = candidates[1]["score"] if len(candidates) > 1 else 0.0
    margin = top["score"] - second
    if top["score"] < LOW_SCORE_THRESHOLD:
        return "NO MATCH", ["Best candidate is below the minimum retrieval threshold (0.60)."]
    if top["score"] < HIGH_SCORE_THRESHOLD:
        reasons.append("Best candidate is in the review band (0.60–0.81).")
    if margin < MIN_TOP_TWO_MARGIN and len(candidates) > 1:
        reasons.append(f"Top-two score margin is only {margin:.3f}; multiple episodes may fit.")
    if top["content_score"] < 0.70:
        reasons.append("Title or metadata similarity contributes materially; source dialogue evidence is not strong enough on its own.")
    evidence_text = normalize(top.get("evidence", {}).get("text", ""))
    # A caption may contain campaign copy not spoken in the show; exact support checks transcript only.
    query_text = normalize(_as_text(promo.get("transcript_raw", "")))
    if len(tokens) >= MIN_MEANINGFUL_TOKENS and query_text and query_text in evidence_text and top["score"] >= HIGH_SCORE_THRESHOLD and margin >= MIN_TOP_TWO_MARGIN:
        reasons.append("Distinctive promo text is present in the cited screenplay evidence.")
        return "VERIFIED", reasons
    if not reasons:
        reasons.append("Candidate is plausible, but the available evidence does not meet the verification rule.")
    return "NEEDS REVIEW", reasons
