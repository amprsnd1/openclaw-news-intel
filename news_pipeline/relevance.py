from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence
import re

GENERIC_CONTEXT_TERMS = {
    "ukraine",
    "ukrainian",
    "russia",
    "russian",
    "eu",
    "europe",
    "us",
    "united states",
    "war",
    "sanctions",
    "nato",
    "kyiv",
    "moscow",
}

# Extra-strict direct-match pool for this watchlist to avoid broad sanctions-only noise.
EUROPE_RU_WAR_DIRECT_CORE_TERMS = {
    "war preparation",
    "military readiness",
    "defense readiness",
    "defence readiness",
    "civil defense",
    "civil defence",
    "mobilization",
    "mobilisation",
    "conscription",
    "reservists",
    "territorial defense",
    "emergency preparedness",
    "war economy",
    "defense industrial base",
    "defence industrial base",
    "ammunition production",
    "artillery shells",
    "air defense",
    "air defence",
    "missile defense",
    "missile defence",
    "drone defense",
    "drone defence",
    "military procurement",
    "defense spending",
    "defence spending",
    "defense budget",
    "defence budget",
    "nato spending target",
    "rearmament",
    "forward deployment",
    "troop deployment",
    "military exercises",
    "joint exercises",
    "readiness exercise",
    "cyberattack",
    "cyber attack",
    "cyber defense",
    "cyber defence",
    "sabotage",
    "critical infrastructure",
    "undersea cables",
    "energy infrastructure",
    "railway sabotage",
    "electronic warfare",
    "gps jamming",
    "border incident",
    "airspace violation",
    "drone incursion",
    "evacuation plan",
    "shelter plan",
    "civil protection drill",
    "military doctrine",
    "national security strategy",
}


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize_text(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _normalize_term(term: str) -> str:
    return " ".join(tokenize_text(term))


def _contains_term_tokens(tokens: Sequence[str], term_tokens: Sequence[str]) -> bool:
    if not term_tokens:
        return False
    if len(term_tokens) == 1:
        return term_tokens[0] in set(tokens)

    n = len(term_tokens)
    for idx in range(0, max(len(tokens) - n + 1, 0)):
        if list(tokens[idx : idx + n]) == list(term_tokens):
            return True
    return False


def match_terms_in_text(text: str, terms: Iterable[str]) -> List[str]:
    tokens = tokenize_text(text)
    matched: List[str] = []
    seen = set()

    for term in terms or []:
        norm = _normalize_term(str(term))
        if not norm or norm in seen:
            continue
        term_tokens = norm.split()
        if _contains_term_tokens(tokens, term_tokens):
            matched.append(norm)
            seen.add(norm)

    return matched


def match_terms_in_fields(fields: Iterable[str], terms: Iterable[str]) -> List[str]:
    joined = "\n".join([f for f in fields if f])
    return match_terms_in_text(joined, terms)


def classify_search_result(query_terms: List[str], matched_terms: List[str]) -> str:
    if not matched_terms:
        return "no_match"
    if len(matched_terms) == len(query_terms):
        return "direct_match"
    if len(matched_terms) >= 2:
        return "strong_partial_match"

    only = matched_terms[0]
    if only in {"us", "eu"}:
        return "weak_partial_match"
    if only in GENERIC_CONTEXT_TERMS:
        return "weak_partial_match"
    return "weak_partial_match"


def classify_watchlist_article(article: Dict[str, Any], watchlist: Dict[str, Any]) -> Dict[str, Any]:
    fields = [
        article.get("title", ""),
        article.get("summary", ""),
        article.get("text", ""),
    ]

    context_terms = watchlist.get("context_terms") or watchlist.get("keywords") or []
    core_terms = watchlist.get("core_terms") or watchlist.get("keywords") or []
    event_terms = watchlist.get("event_triggers") or []
    financial_terms = watchlist.get("financial_and_policy_terms") or []

    matched_context = match_terms_in_fields(fields, context_terms)
    matched_core = match_terms_in_fields(fields, core_terms)
    matched_event = match_terms_in_fields(fields, event_terms)
    matched_financial = match_terms_in_fields(fields, financial_terms)

    # For europe_ru_war_preparations we tighten direct matches to readiness-style terms.
    watchlist_name = (watchlist.get("name") or "").strip().lower()
    if watchlist_name == "europe_ru_war_preparations":
        # Explicitly gate direct matches to readiness-style signals only.
        direct_pool = match_terms_in_fields(fields, EUROPE_RU_WAR_DIRECT_CORE_TERMS)
    else:
        direct_pool = matched_core + matched_event + matched_financial
    has_context = bool(matched_context)
    has_direct_core = bool(direct_pool)

    if has_context and has_direct_core:
        relevance = "direct_match"
    elif has_context or matched_core or matched_event or matched_financial:
        relevance = "near_miss"
    else:
        relevance = "noise"

    return {
        "relevance_class": relevance,
        "matched_context_terms": sorted(set(matched_context)),
        "matched_core_terms": sorted(set(matched_core)),
        "matched_event_triggers": sorted(set(matched_event)),
        "matched_financial_terms": sorted(set(matched_financial)),
    }
