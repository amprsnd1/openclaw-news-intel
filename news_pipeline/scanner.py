from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import quote_plus

import feedparser

from .collector import access_mode_for_url, build_gdelt_topic_query_plan, source_for_url
from .ingest.gdelt import fetch_gdelt_query
from .ingest.rss import fetch_rss
from .normalize import normalize_article, title_hash, utc_now_iso
from .relevance import GENERIC_CONTEXT_TERMS, match_terms_in_fields
from .storage import Storage

SIGNAL_RANK = {"high_signal": 3, "medium_signal": 2, "low_signal": 1, "noise": 0}
MIN_CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}
SOURCE_QUALITY_RANK = {"low": 1, "medium": 2, "high": 3}
VIRTUAL_SCAN_SOURCES = {"rss", "google_news_rss", "gdelt"}

NOISE_HINTS = {
    "sport",
    "sports",
    "football",
    "soccer",
    "celebrity",
    "movie",
    "music",
    "mosaic",
    "restoration",
    "recipe",
    "fashion",
}

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

SCAN_TERM_ALIASES = {
    "europe_ru_war_preparations": {
        "core": ["troops", "military deployment"],
        "event": ["deploys troops", "troop deployment"],
    }
}

SCAN_WEAK_CORE_TERMS = {
    "europe_ru_war_preparations": {
        "shadow fleet",
        "sanctions enforcement",
        "sanctions",
    }
}

EUROPE_WAR_PREP_ANCHOR_TERMS = [
    "Russia",
    "Russian",
    "Russia threat",
    "NATO",
    "Eastern Europe",
    "Poland",
    "Baltics",
    "Ukraine war spillover",
    "readiness",
    "procurement",
    "air defense",
    "air defence",
    "missile defense",
    "missile defence",
    "drone defense",
    "counter-drone",
    "FCAS",
    "fighter jet",
    "defense budget",
    "defence budget",
    "defense spending",
    "defence spending",
    "troop deployment",
    "civil defense",
    "civil defence",
    "mobilization",
    "critical infrastructure",
    "sabotage",
    "cyberattack",
    "ammunition",
]

HARD_GATES = {
    "ukraine_financing": {
        "context": ["Ukraine", "Ukrainian", "Kyiv", "Zelenskyy", "Ukraine Facility"],
        "required": [
            "IMF",
            "loan",
            "loans",
            "tranche",
            "disbursement",
            "budget support",
            "macro financial assistance",
            "frozen Russian assets",
            "frozen assets",
            "windfall profits",
            "EU loan",
            "G7 loan",
            "debt",
            "bond",
            "bonds",
            "restructuring",
            "donor funding",
            "grant",
            "guarantees",
            "fiscal gap",
        ],
        "missing_context": "no Ukraine context",
        "missing_required": "no financing terms",
    },
    "europe_ru_war_preparations": {
        "context": [
            "Europe",
            "European",
            "EU",
            "NATO",
            "Poland",
            "Polish",
            "Baltics",
            "Baltic",
            "Estonia",
            "Estonian",
            "Latvia",
            "Latvian",
            "Lithuania",
            "Lithuanian",
            "Finland",
            "Finnish",
            "Sweden",
            "Swedish",
            "Germany",
            "German",
            "France",
            "French",
            "Romania",
            "Romanian",
            "Moldova",
            "Moldovan",
            "UK",
            "British",
            "Britain",
            "United Kingdom",
            "Spain",
            "Spanish",
            "Italy",
            "Italian",
            "Czech",
            "Slovakia",
            "Slovak",
            "Bulgaria",
            "Bulgarian",
            "Norway",
            "Norwegian",
            "Denmark",
            "Danish",
            "Netherlands",
            "Dutch",
            "Eastern Europe",
            "European Commission",
            "European Council",
            "Russia threat",
            "Russian threat",
            "Ukraine war",
            "Ukraine war spillover",
        ],
        "required": [
            "defense budget",
            "defence budget",
            "defense spending",
            "defence spending",
            "procurement",
            "air defense",
            "air defence",
            "ammunition",
            "artillery shells",
            "rearmament",
            "military readiness",
            "troops",
            "deploys troops",
            "troop deployment",
            "NATO deployment",
            "civil defense",
            "civil defence",
            "mobilization",
            "reservists",
            "critical infrastructure",
            "sabotage",
            "cyberattack",
            "hybrid warfare",
            "rail infrastructure",
            "undersea cables",
            "energy infrastructure",
            "military logistics",
            "defense industrial base",
            "defence industrial base",
            "war economy",
            "readiness",
            "drone defense",
            "counter-drone",
            "missile defense",
            "missile defence",
            "FCAS",
            "fighter jet",
            "warship",
            "frigate",
            "submarine",
            "tank production",
            "munition production",
        ],
        "missing_context": "no Europe/NATO/member-state context",
        "missing_required": "missing war-preparation core term",
    },
    "global_trade_and_country_flows": {
        "context": [
            "global",
            "country",
            "China",
            "United States",
            "US",
            "EU",
            "Europe",
            "eurozone",
            "ECB",
            "India",
            "Japan",
            "South Korea",
            "Vietnam",
            "Mexico",
            "Canada",
            "Brazil",
            "Turkey",
            "Russia",
            "Iran",
            "Gulf",
            "Red Sea",
            "Strait of Hormuz",
        ],
        "required": [
            "tariff",
            "tariffs",
            "trade war",
            "trade deficit",
            "trade surplus",
            "exports",
            "imports",
            "export controls",
            "sanctions",
            "secondary sanctions",
            "shipping",
            "shipping lanes",
            "container rates",
            "freight",
            "supply chain",
            "Red Sea",
            "Suez Canal",
            "Panama Canal",
            "Strait of Hormuz",
            "Hormuz",
            "oil flows",
            "oil",
            "oil prices",
            "LNG",
            "grain exports",
            "rare earths",
            "semiconductors",
            "inflation",
            "rates",
            "interest rates",
            "bond yields",
            "commodities",
            "customs",
            "WTO",
            "anti-dumping",
            "industrial policy",
            "subsidies",
        ],
        "missing_context": "no country/global trade context",
        "missing_required": "no trade, shipping, sanctions, commodity-flow, or supply-chain term",
    },
    "eu_energy_security": {
        "context": [
            "EU",
            "Europe",
            "European",
            "eurozone",
            "Germany",
            "France",
            "Poland",
            "Baltics",
            "Netherlands",
            "Italy",
            "Spain",
            "LNG Europe",
            "European gas",
            "EU energy",
        ],
        "required": [
            "gas",
            "LNG",
            "oil",
            "electricity",
            "power grid",
            "energy security",
            "gas storage",
            "pipeline",
            "sanctions",
            "energy prices",
            "renewables",
            "nuclear",
            "blackout",
            "supply risk",
            "Russian gas",
        ],
        "missing_context": "no EU/Europe/member-state energy-security context",
        "missing_required": "no energy, security, or supply term",
    },
    "china_taiwan_risk": {
        "context": [
            "China",
            "Chinese",
            "Taiwan",
            "Taiwanese",
            "Taipei",
            "Beijing",
            "PLA",
            "Indo-Pacific",
            "South China Sea",
            "East China Sea",
            "Pacific",
            "TSMC",
            "semiconductor supply chain",
        ],
        "required": [
            "military",
            "blockade",
            "sanctions",
            "export controls",
            "chips",
            "chip",
            "Taiwan Strait",
            "PLA",
            "naval",
            "air drills",
            "missile",
            "warships",
            "fighter jets",
            "semiconductor",
            "TSMC",
        ],
        "missing_context": "no China/Taiwan/PLA/Pacific/semiconductor context",
        "missing_required": "no China-Taiwan military, blockade, sanctions, export-control, chip, or Strait term",
    },
    "iran_war_risk": {
        "context": [
            "Iran",
            "Iranian",
            "Tehran",
            "IRGC",
            "Islamic Revolutionary Guard",
            "Quds Force",
            "Israel",
            "Israeli",
            "US forces",
            "US base",
            "US forces in Iraq",
            "US forces in Syria",
            "Gulf",
            "Persian Gulf",
            "Hormuz",
            "Strait of Hormuz",
            "Red Sea",
            "Hezbollah",
            "Houthis",
            "Houthi",
            "Iraqi militia",
            "nuclear enrichment",
            "uranium enrichment",
            "Natanz",
            "Fordow",
            "IAEA Iran",
        ],
        "required": [
            "strike",
            "airstrike",
            "strikes",
            "missile",
            "drone attack",
            "retaliation",
            "war",
            "escalation",
            "base attack",
            "proxy attack",
            "tanker",
            "shipping attack",
            "nuclear facility",
            "sanctions escalation",
            "military response",
        ],
        "missing_context": "missing Iran/Gulf/proxy context",
        "missing_required": "missing war/escalation core term",
    },
    "migration_policy_europe": {
        "context": [
            "Europe",
            "European Union",
            "EU",
            "Schengen",
            "Germany",
            "France",
            "Italy",
            "Spain",
            "Poland",
            "Netherlands",
            "Sweden",
            "Denmark",
            "Austria",
            "Greece",
            "Hungary",
            "Finland",
            "Ireland",
            "United Kingdom",
            "UK",
            "Norway",
            "Switzerland",
        ],
        "required": [
            "migration",
            "immigration",
            "asylum",
            "deportation",
            "returns",
            "return hubs",
            "border controls",
            "Schengen",
            "visa",
            "residence permit",
            "work permit",
            "EU migration pact",
            "refugee quota",
            "Frontex",
            "safe third country",
            "illegal migration",
            "irregular migration",
        ],
        "missing_context": "no Europe/EU/country context",
        "missing_required": "no migration policy term",
    },
}

HIGH_RISK_TOPICS = {"iran_war_risk", "china_taiwan_risk", "europe_ru_war_preparations"}

MARKET_OWNERSHIP_TERMS = [
    "inflation",
    "rates",
    "interest rates",
    "bond yields",
    "commodities",
    "oil",
    "oil prices",
    "oil flows",
    "shipping",
    "Hormuz",
    "Strait of Hormuz",
    "freight",
    "container rates",
    "supply chain",
    "sanctions",
    "secondary sanctions",
]

MARKET_PRIMARY_TERMS = [
    "inflation",
    "rates",
    "interest rates",
    "bond yields",
    "commodities",
    "oil prices",
    "oil flows",
]

IRAN_ESCALATION_TERMS = [
    "strike",
    "strikes",
    "missile",
    "drone",
    "retaliation",
    "base",
    "bases",
    "proxy",
    "air defense",
    "air defence",
    "nuclear",
    "tanker",
]

SPILLOVER_LABEL_TERMS = {
    "inflation": ["inflation", "rates", "interest rates", "bond yields"],
    "oil": ["oil", "oil prices", "oil flows", "Brent", "WTI"],
    "shipping": ["shipping", "Hormuz", "Strait of Hormuz", "Red Sea", "Suez", "freight", "container rates"],
    "energy": ["gas", "LNG", "electricity", "power grid", "energy prices", "pipeline"],
    "security": ["strike", "missile", "drone", "retaliation", "base", "sabotage", "cyberattack"],
    "semiconductors": ["semiconductor", "semiconductors", "chips", "TSMC"],
}


def parse_since_window(value: str | None) -> tuple[datetime, str, int]:
    raw = (value or "6h").strip().lower()
    if not raw:
        raw = "6h"
    unit = raw[-1]
    number = raw[:-1]
    try:
        amount = int(number)
    except ValueError as exc:
        raise ValueError("since must be like 2h, 24h, or 7d") from exc
    if amount < 0:
        raise ValueError("since must be positive")
    if unit == "h":
        delta = timedelta(hours=amount)
    elif unit == "d":
        delta = timedelta(days=amount)
    elif unit == "m":
        delta = timedelta(minutes=amount)
    else:
        raise ValueError("since must use m, h, or d")
    return datetime.now(timezone.utc) - delta, raw, int(delta.total_seconds())


def _dt_from_iso(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_recent(article: Dict[str, Any], since_dt: datetime) -> bool:
    return _dt_from_iso(article.get("published_at", "")) >= since_dt


def scan_key(topic: str | None, query: str | None, sources: Iterable[str], since_label: str) -> str:
    subject = f"topic:{topic}" if topic else f"query:{query}"
    source_key = ",".join(sorted(s.strip().lower() for s in sources if s.strip()))
    return f"{subject}|sources:{source_key}|window:{since_label}".lower()


def watchlist_scan_terms(watchlist: Dict[str, Any] | None, query: str | None = None) -> Dict[str, List[str]]:
    if watchlist:
        aliases = SCAN_TERM_ALIASES.get((watchlist.get("name") or "").strip().lower(), {})
        return {
            "context": list(watchlist.get("context_terms") or watchlist.get("keywords") or []) + list(aliases.get("context", [])),
            "core": list(watchlist.get("core_terms") or watchlist.get("keywords") or []) + list(aliases.get("core", [])),
            "event": list(watchlist.get("event_triggers") or []) + list(aliases.get("event", [])),
            "financial": list(watchlist.get("financial_and_policy_terms") or []) + list(aliases.get("financial", [])),
            "suggested_queries": list(watchlist.get("suggested_queries") or []),
        }
    terms = [t for t in (query or "").split() if t]
    return {
        "context": terms,
        "core": terms,
        "event": [],
        "financial": [],
        "suggested_queries": [query or ""],
    }


def _watchlist_name(watchlist: Dict[str, Any] | None) -> str:
    return (watchlist or {}).get("name", "").strip().lower()


def _hard_gate_result(watchlist_name: str, fields: List[str]) -> Dict[str, Any] | None:
    gate = HARD_GATES.get(watchlist_name)
    if not gate:
        return None
    matched_context = match_terms_in_fields(fields, gate["context"])
    matched_required = match_terms_in_fields(fields, gate["required"])
    missing: List[str] = []
    if not matched_context:
        missing.append(gate["missing_context"])
    if not matched_required:
        missing.append(gate["missing_required"])
    return {
        "passed": not missing,
        "matched_gate_context_terms": sorted(set(matched_context)),
        "matched_gate_required_terms": sorted(set(matched_required)),
        "missing_required_terms": missing,
    }


def _rejection_payload(reason: str, missing: List[str] | None = None, demoted: bool = False) -> Dict[str, Any]:
    return {
        "signal_class": "noise",
        "matched_terms": [],
        "matched_context_terms": [],
        "matched_core_terms": [],
        "matched_event_triggers": [],
        "matched_financial_terms": [],
        "missing_required_terms": missing or [],
        "why": reason,
        "reject_reason": reason,
        "rejection_kind": "Demoted" if demoted else "Rejected",
    }


def classify_signal(article: Dict[str, Any], watchlist: Dict[str, Any] | None = None, query: str | None = None) -> Dict[str, Any]:
    title = article.get("title", "")
    summary = article.get("summary", "")
    source = article.get("source", "")
    fields = [title, summary, source]
    lower_blob = " ".join(fields).lower()

    if any(hint in lower_blob for hint in NOISE_HINTS):
        return {
            "signal_class": "noise",
            "matched_terms": [],
            "matched_context_terms": [],
            "matched_core_terms": [],
            "matched_event_triggers": [],
            "matched_financial_terms": [],
            "why": "Excluded as unrelated headline noise.",
        }

    terms = watchlist_scan_terms(watchlist, query=query)
    matched_context = match_terms_in_fields(fields, terms["context"])
    matched_core = match_terms_in_fields(fields, terms["core"])
    matched_event = match_terms_in_fields(fields, terms["event"])
    matched_financial = match_terms_in_fields(fields, terms["financial"])
    matched_all = sorted(set(matched_context + matched_core + matched_event + matched_financial))

    source_quality = str(article.get("source_quality") or "medium").lower()

    if not watchlist:
        query_terms = [str(t).lower() for t in (query or "").split() if t]
        matched = match_terms_in_fields(fields, query_terms)
        if not matched:
            signal = "noise"
            why = "No query terms matched the headline or summary."
        elif len(matched) >= 3 or len(matched) == len(set(query_terms)):
            signal = "high_signal"
            why = "Matched most query terms in headline metadata."
        elif len(matched) >= 2:
            signal = "medium_signal"
            why = "Matched multiple query terms in headline metadata."
        else:
            only = matched[0]
            signal = "low_signal"
            why = "Only one query term matched; useful only as an adjacent signal."
            if only in GENERIC_CONTEXT_TERMS:
                why = "Only one generic context term matched."
        if signal == "medium_signal" and source_quality == "high":
            signal = "high_signal"
            why += " High-quality source increased signal priority."
        return {
            "signal_class": signal,
            "matched_terms": sorted(set(matched)),
            "matched_context_terms": sorted(set(matched)),
            "matched_core_terms": [],
            "matched_event_triggers": [],
            "matched_financial_terms": [],
            "why": why,
        }

    watchlist_name = _watchlist_name(watchlist)
    strict_fields = [title, summary]
    gate = _hard_gate_result(watchlist_name, strict_fields)
    if gate and not gate["passed"]:
        reason = "; ".join(gate["missing_required_terms"])
        if matched_all or gate["matched_gate_context_terms"] or gate["matched_gate_required_terms"]:
            reason = f"Hard gate failed for {watchlist_name}: {reason}."
        else:
            reason = f"Rejected from {watchlist_name}: {reason}."
        payload = _rejection_payload(reason, gate["missing_required_terms"])
        payload.update(
            {
                "matched_terms": matched_all,
                "matched_context_terms": sorted(set(matched_context + gate["matched_gate_context_terms"])),
                "matched_core_terms": sorted(set(matched_core)),
                "matched_event_triggers": sorted(set(matched_event)),
                "matched_financial_terms": sorted(set(matched_financial + gate["matched_gate_required_terms"])),
            }
        )
        return payload
    if gate and gate["passed"]:
        if watchlist_name in {"iran_war_risk", "europe_ru_war_preparations"}:
            title_gate = _hard_gate_result(watchlist_name, [title])
            if title_gate and not title_gate["passed"]:
                title_missing = [f"headline {item}" for item in title_gate["missing_required_terms"]]
                reason = f"Hard gate failed for {watchlist_name}: {'; '.join(title_missing)}."
                payload = _rejection_payload(reason, title_missing)
                payload.update(
                    {
                        "matched_terms": matched_all,
                        "matched_context_terms": sorted(set(matched_context + gate["matched_gate_context_terms"])),
                        "matched_core_terms": sorted(set(matched_core)),
                        "matched_event_triggers": sorted(set(matched_event)),
                        "matched_financial_terms": sorted(set(matched_financial + gate["matched_gate_required_terms"])),
                    }
                )
                return payload
        matched_context = sorted(set(matched_context + gate["matched_gate_context_terms"]))
        matched_core = sorted(set(matched_core + gate["matched_gate_required_terms"]))
        matched_all = sorted(set(matched_all + gate["matched_gate_context_terms"] + gate["matched_gate_required_terms"]))

    if watchlist_name == "europe_ru_war_preparations" and gate and gate["passed"]:
        anchors = match_terms_in_fields(strict_fields, EUROPE_WAR_PREP_ANCHOR_TERMS)
        if not anchors:
            return {
                "signal_class": "low_signal",
                "matched_terms": matched_all,
                "matched_context_terms": sorted(set(matched_context + gate["matched_gate_context_terms"])),
                "matched_core_terms": sorted(set(matched_core + gate["matched_gate_required_terms"])),
                "matched_event_triggers": sorted(set(matched_event)),
                "matched_financial_terms": sorted(set(matched_financial)),
                "missing_required_terms": ["no explicit Europe/Russia/NATO readiness, procurement, deployment, infrastructure, cyber, sabotage, or mobilization anchor"],
                "why": "Generic defense or security item; demoted because it lacks an explicit Europe/Russia/NATO war-preparation anchor.",
            }

    weak_core_only = bool(matched_core) and set(matched_core).issubset(SCAN_WEAK_CORE_TERMS.get(watchlist_name, set()))

    if not matched_all:
        signal = "noise"
        why = "No watchlist terms matched headline metadata."
    elif weak_core_only and not (matched_event or matched_financial):
        signal = "low_signal"
        why = "Matched weak sanctions/shadow-fleet terms without concrete readiness, procurement, deployment, or infrastructure signal."
    elif matched_context and (matched_event or matched_financial):
        signal = "high_signal"
        why = "Matched watchlist context plus event or policy trigger in headline metadata."
    elif matched_context and len(set(matched_core)) >= 2:
        signal = "high_signal"
        why = "Matched watchlist context plus multiple core signal terms."
    elif matched_context and matched_core:
        signal = "medium_signal"
        why = "Matched watchlist context plus a core signal term."
    elif matched_context or matched_core or matched_event or matched_financial:
        signal = "low_signal"
        why = "Matched adjacent watchlist terms without enough context/core linkage."
    else:
        signal = "noise"
        why = "No relevant signal found."

    if (
        signal == "medium_signal"
        and watchlist_name == "iran_war_risk"
        and gate
        and gate["passed"]
        and match_terms_in_fields(strict_fields, ["Hormuz", "Strait of Hormuz"])
        and match_terms_in_fields(strict_fields, ["strike", "strikes", "missile", "tanker", "shipping attack"])
    ):
        signal = "high_signal"
        why += " Hormuz escalation terms increased signal priority."
    elif (
        signal == "medium_signal"
        and watchlist_name == "europe_ru_war_preparations"
        and gate
        and gate["passed"]
        and match_terms_in_fields(strict_fields, ["NATO"])
        and match_terms_in_fields(strict_fields, ["Eastern Europe", "Russia threat", "Russian threat"])
        and match_terms_in_fields(strict_fields, ["troops", "troop deployment", "NATO deployment", "deploys"])
    ):
        signal = "high_signal"
        why += " NATO eastern-flank deployment terms increased signal priority."
    elif signal == "medium_signal" and source_quality == "high" and not weak_core_only:
        signal = "high_signal"
        why += " High-quality source increased signal priority."
    elif signal == "low_signal" and source_quality == "high" and matched_context and (matched_core or matched_event or matched_financial) and not weak_core_only:
        signal = "medium_signal"
        why += " High-quality source increased adjacent signal priority."

    return {
        "signal_class": signal,
        "matched_terms": matched_all,
        "matched_context_terms": sorted(set(matched_context)),
        "matched_core_terms": sorted(set(matched_core)),
        "matched_event_triggers": sorted(set(matched_event)),
        "matched_financial_terms": sorted(set(matched_financial)),
        "missing_required_terms": [],
        "why": why,
    }


def _article_fields(article: Dict[str, Any]) -> List[str]:
    return [str(article.get("title") or ""), str(article.get("summary") or ""), str(article.get("source") or "")]


def _spillover_labels(article: Dict[str, Any]) -> List[str]:
    fields = _article_fields(article)
    labels: List[str] = []
    for label, terms in SPILLOVER_LABEL_TERMS.items():
        if match_terms_in_fields(fields, terms):
            labels.append(label)
    return labels


def _classification_score(topic: str, classification: Dict[str, Any], article: Dict[str, Any]) -> Tuple[int, int, int, int]:
    fields = _article_fields(article)
    ownership_bonus = 0
    has_market_primary = bool(match_terms_in_fields(fields, MARKET_PRIMARY_TERMS))
    has_escalation = bool(match_terms_in_fields(fields, IRAN_ESCALATION_TERMS))
    if topic == "global_trade_and_country_flows" and has_market_primary:
        ownership_bonus += 2
    elif topic == "global_trade_and_country_flows" and match_terms_in_fields(fields, MARKET_OWNERSHIP_TERMS) and not has_escalation:
        ownership_bonus += 1
    if topic == "iran_war_risk":
        has_market = bool(match_terms_in_fields(fields, MARKET_OWNERSHIP_TERMS))
        if has_escalation:
            ownership_bonus += 2
        if has_market_primary and not has_escalation:
            ownership_bonus -= 2
    if topic == "eu_energy_security" and match_terms_in_fields(fields, ["EU", "Europe", "European", "eurozone", "European gas", "EU energy"]):
        ownership_bonus += 1
    if topic == "china_taiwan_risk" and match_terms_in_fields(fields, ["China", "Taiwan", "PLA", "Pacific", "TSMC"]):
        ownership_bonus += 1
    if topic == "europe_ru_war_preparations" and match_terms_in_fields(fields, ["Russia threat", "NATO", "Eastern Europe", "readiness", "procurement"]):
        ownership_bonus += 1
    return (
        SIGNAL_RANK.get(classification.get("signal_class"), 0),
        ownership_bonus,
        len(classification.get("matched_terms") or []),
        SOURCE_QUALITY_RANK.get(str(classification.get("source_quality") or "medium").lower(), 2),
    )


def classify_across_watchlists(
    article: Dict[str, Any],
    watchlists: List[Dict[str, Any]] | None,
    current_watchlist: Dict[str, Any] | None = None,
    demote_non_primary: bool = True,
) -> Dict[str, Any]:
    topic_scores: List[Tuple[Tuple[int, int, int, int], str, Dict[str, Any]]] = []
    classifications: Dict[str, Dict[str, Any]] = {}
    for watchlist in watchlists or []:
        name = _watchlist_name(watchlist)
        if not name:
            continue
        classification = classify_signal(article, watchlist=watchlist)
        classification["source_quality"] = article.get("source_quality", "medium")
        classifications[name] = classification
        score = _classification_score(name, classification, article)
        if score[0] > 0:
            topic_scores.append((score, name, classification))

    if not topic_scores:
        current_name = _watchlist_name(current_watchlist)
        current = classify_signal(article, watchlist=current_watchlist) if current_watchlist else {}
        current.update({"primary_topic": current_name or None, "secondary_topics": [], "spillover_topics": _spillover_labels(article)})
        return current

    topic_scores.sort(key=lambda item: item[0], reverse=True)
    primary_score, primary_topic, primary_classification = topic_scores[0]
    secondary = [name for score, name, _classification in topic_scores[1:] if score[0] > 0]
    primary_classification = dict(primary_classification)
    primary_classification["primary_topic"] = primary_topic
    primary_classification["secondary_topics"] = secondary
    primary_classification["spillover_topics"] = _spillover_labels(article)

    current_name = _watchlist_name(current_watchlist)
    if demote_non_primary and current_name and current_name != primary_topic:
        current_classification = classifications.get(current_name)
        if current_classification:
            reason = current_classification.get("reject_reason") or f"Primary topic is {primary_topic}; {current_name} is only secondary for this headline."
            if not current_classification.get("reject_reason"):
                reason = f"Primary topic is {primary_topic}; {current_name} is only secondary for this headline."
            demoted = _rejection_payload(reason, current_classification.get("missing_required_terms", []), demoted=True)
            demoted.update(
                {
                    "matched_terms": current_classification.get("matched_terms", []),
                    "matched_context_terms": current_classification.get("matched_context_terms", []),
                    "matched_core_terms": current_classification.get("matched_core_terms", []),
                    "matched_event_triggers": current_classification.get("matched_event_triggers", []),
                    "matched_financial_terms": current_classification.get("matched_financial_terms", []),
                    "primary_topic": primary_topic,
                    "secondary_topics": secondary,
                    "spillover_topics": _spillover_labels(article),
                }
            )
            return demoted
    return primary_classification


def _source_cfg_for_article(raw: Dict[str, Any], fallback_source: str, access_mode: str = "rss") -> Dict[str, Any]:
    return {
        "name": raw.get("source") or fallback_source,
        "language": raw.get("language", "unknown"),
        "country": raw.get("country", ""),
        "access_mode": raw.get("access_mode") or access_mode,
    }


def _store_candidate(
    storage: Storage,
    raw: Dict[str, Any],
    source_cfg: Dict[str, Any],
    discovery_source: str,
    discovery_query: str | None = None,
) -> Dict[str, Any] | None:
    article = normalize_article(raw, source_cfg)
    if not article.get("title") or not article.get("url"):
        return None
    inserted = storage.insert_article(article)
    article_id = article["id"] if inserted else storage.article_id_for(article.get("url", ""), article.get("title", ""))
    if not article_id:
        return None
    article["id"] = article_id
    storage.upsert_article_metadata(
        article_id,
        {
            "discovery_source": discovery_source,
            "discovery_query": discovery_query,
            "access_mode": article.get("access_mode"),
            "enrichment_status": "not_attempted",
        },
    )
    return article


def _dedupe_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: List[Dict[str, Any]] = []
    for item in candidates:
        url = item.get("url", "")
        thash = title_hash(item.get("title", ""))
        key = item.get("id", "")
        if url and url in seen_urls:
            continue
        if thash and thash in seen_titles:
            continue
        if key and any(existing.get("id") == key for existing in unique):
            continue
        seen_urls.add(url)
        seen_titles.add(thash)
        unique.append(item)
    return unique


def _google_news_items(query: str, max_items: int, config: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    cfg = config or {}
    parsed = feedparser.parse(
        GOOGLE_NEWS_RSS_URL.format(query=quote_plus(query)),
        request_headers={"User-Agent": str(cfg.get("user_agent", "news-intel local research tool"))},
    )
    items: List[Dict[str, Any]] = []
    for entry in parsed.entries[:max_items]:
        source = "Google News RSS"
        source_info = entry.get("source")
        if isinstance(source_info, dict):
            source = source_info.get("title") or source
        items.append(
            {
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "published": entry.get("published") or entry.get("updated") or "",
                "author": "",
                "summary": entry.get("summary", "") or entry.get("description", ""),
                "text": "",
                "language": "en",
                "country": "",
                "source": source,
                "access_mode": "public_metadata",
            }
        )
    return items


def _gdelt_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for article in payload.get("articles") or []:
        url = article.get("url", "")
        items.append(
            {
                "title": article.get("title", ""),
                "url": url,
                "published": article.get("seendate") or "",
                "author": "",
                "summary": article.get("snippet", "") or "",
                "text": "",
                "language": article.get("language", "unknown") or "unknown",
                "country": article.get("sourcecountry", "") or "",
                "source": source_for_url(url),
                "access_mode": "metadata_only" if access_mode_for_url(url) == "metadata_only" else "public_metadata",
            }
        )
    return items


def _queries_for_scan(watchlist: Dict[str, Any] | None, query: str | None, max_queries: int) -> List[Dict[str, str]]:
    if query:
        return [{"query": query, "source": "free_form_query"}]
    if not watchlist:
        return []
    return build_gdelt_topic_query_plan(watchlist, max_queries=max_queries)


def _source_status_template(sources: Iterable[str]) -> Dict[str, str]:
    statuses = {"rss": "skipped", "google_news_rss": "skipped", "gdelt": "skipped", "fundus": "not used for scan"}
    for source in sources:
        if source in statuses:
            statuses[source] = "pending"
    return statuses


def _source_key(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "_").replace("/", "_")


def _source_matches_ref(source_cfg: Dict[str, Any], ref: str) -> bool:
    key = _source_key(ref)
    return key in {
        _source_key(str(source_cfg.get("id", ""))),
        _source_key(str(source_cfg.get("name", ""))),
        _source_key(str(source_cfg.get("category", ""))),
    }


def resolve_scan_sources(
    requested: str | None,
    sources_cfg: List[Dict[str, Any]],
    source_groups: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    groups = source_groups or {}
    source_refs = [s.strip() for s in (requested or "rss").split(",") if s.strip()] or ["rss"]
    virtual_sources: set[str] = set()
    selected_ids: set[str] = set()
    selected_rss: List[Dict[str, Any]] = []
    unknown: List[str] = []
    group_counts: Dict[str, Dict[str, int]] = {}

    def add_rss_source(source_cfg: Dict[str, Any]) -> None:
        if not source_cfg.get("enabled", True):
            return
        if source_cfg.get("adapter", "rss") != "rss":
            return
        sid = _source_key(str(source_cfg.get("id") or source_cfg.get("name")))
        if sid in selected_ids:
            return
        selected_ids.add(sid)
        selected_rss.append(source_cfg)

    def group_ref_enabled(group_ref: str) -> bool:
        group_key = _source_key(group_ref)
        if group_key in {"google_news_rss", "gdelt"}:
            return True
        if group_key == "rss":
            return any(
                source_cfg.get("enabled", True) and source_cfg.get("adapter", "rss") == "rss"
                for source_cfg in sources_cfg
            )
        return any(
            _source_matches_ref(source_cfg, group_ref)
            and source_cfg.get("enabled", True)
            and source_cfg.get("adapter", "rss") == "rss"
            for source_cfg in sources_cfg
        )

    for ref in source_refs:
        key = _source_key(ref)
        if key in VIRTUAL_SCAN_SOURCES:
            virtual_sources.add(key)
            if key == "rss":
                for source_cfg in sources_cfg:
                    add_rss_source(source_cfg)
            continue
        if key in groups:
            group_refs = [str(group_ref) for group_ref in groups[key].get("sources", [])]
            for group_ref in group_refs:
                group_key = _source_key(str(group_ref))
                if group_key in VIRTUAL_SCAN_SOURCES:
                    virtual_sources.add(group_key)
                    if group_key == "rss":
                        for source_cfg in sources_cfg:
                            add_rss_source(source_cfg)
                    continue
                matched = False
                for source_cfg in sources_cfg:
                    if _source_matches_ref(source_cfg, str(group_ref)):
                        add_rss_source(source_cfg)
                        matched = True
                if not matched and group_key not in VIRTUAL_SCAN_SOURCES:
                    continue
            group_counts[key] = {
                "configured": len(group_refs),
                "enabled": sum(1 for group_ref in group_refs if group_ref_enabled(group_ref)),
            }
            continue
        matched_direct = False
        for source_cfg in sources_cfg:
            if _source_matches_ref(source_cfg, ref):
                add_rss_source(source_cfg)
                matched_direct = True
        if not matched_direct:
            unknown.append(ref)

    if unknown:
        available = sorted(set(list(groups.keys()) + list(VIRTUAL_SCAN_SOURCES)))
        raise ValueError(f"Unknown scan source/group: {', '.join(unknown)}. Available source groups: {', '.join(available)}")

    return {
        "requested": [_source_key(r) for r in source_refs],
        "virtual_sources": virtual_sources,
        "rss_sources": selected_rss,
        "group_counts": group_counts,
    }


def _quality_for_source(source_cfg: Dict[str, Any], source_quality: Dict[str, str] | None) -> str:
    quality = source_quality or {}
    category = _source_key(str(source_cfg.get("category", "")))
    source_id = _source_key(str(source_cfg.get("id", "")))
    adapter = _source_key(str(source_cfg.get("adapter", "")))
    return quality.get(category) or quality.get(source_id) or quality.get(adapter) or quality.get("generic_rss", "low")


def _source_family(source: str) -> str:
    value = (source or "").strip().lower()
    for suffix in (" ltd", " inc", ".com", ".org", ".net"):
        value = value.replace(suffix, "")
    return value.split(" - ")[0].split("|")[0].strip() or "unknown"


def source_diversity_note(topic: str | None, high_signals: List[Dict[str, Any]]) -> str | None:
    if not topic or topic not in HIGH_RISK_TOPICS or not high_signals:
        return None
    families = {_source_family(str(row.get("source") or "")) for row in high_signals}
    has_high_quality = any(str(row.get("source_quality") or "").lower() == "high" for row in high_signals)
    if len(families) >= 2:
        return "Confirmed cluster: multiple independent sources."
    if not has_high_quality:
        return "Warning: high alert based on limited source diversity."
    return "High-quality source present, but source diversity is limited."


def _summary_status(high: int, medium: int, low: int, rejected: int) -> str:
    if high >= 3:
        return "HIGH ALERT"
    if high or medium:
        return "Active"
    if low:
        return "Quiet"
    if rejected:
        return "No direct signals"
    return "Quiet"


def _cache_is_fresh(fetched_at: str, ttl_minutes: int) -> bool:
    try:
        fetched = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    return datetime.now(timezone.utc) - fetched.astimezone(timezone.utc) <= timedelta(minutes=ttl_minutes)


def run_scan(
    storage: Storage,
    sources_cfg: List[Dict[str, Any]],
    watchlist: Dict[str, Any] | None,
    query: str | None,
    since: str = "6h",
    max_items: int = 50,
    sources: str | None = None,
    min_confidence: str = "low",
    only_new: bool = True,
    show_seen: bool = False,
    max_queries: int = 1,
    use_cache_first: bool = False,
    gdelt_config: Dict[str, Any] | None = None,
    google_news_config: Dict[str, Any] | None = None,
    source_groups: Dict[str, Dict[str, Any]] | None = None,
    source_quality: Dict[str, str] | None = None,
    all_watchlists: List[Dict[str, Any]] | None = None,
    show_rejected: bool = False,
    primary_only: bool = False,
    group_by_primary: bool = False,
) -> Dict[str, Any]:
    since_dt, since_label, _ = parse_since_window(since)
    default_sources_used = False
    if sources is None and watchlist and watchlist.get("default_scan_sources"):
        sources = ",".join(str(item) for item in watchlist.get("default_scan_sources") or [])
        default_sources_used = True
    if sources is None:
        sources = "rss"
    resolved = resolve_scan_sources(sources, sources_cfg, source_groups=source_groups)
    source_list = resolved["requested"]
    virtual_sources = resolved["virtual_sources"]
    rss_sources = resolved["rss_sources"]

    statuses = _source_status_template(source_list)
    warnings: List[str] = []
    for group_name, counts in resolved.get("group_counts", {}).items():
        if counts.get("enabled", 0) == 0:
            warnings.append(f"{group_name} has no enabled live sources.")
    candidates: List[Dict[str, Any]] = []
    scanned_counts = {"rss": 0, "google_news_rss": 0, "gdelt": 0}
    topic_name = watchlist.get("name") if watchlist else None
    key = scan_key(topic_name, query, source_list, since_label)

    if rss_sources:
        try:
            for source_cfg in rss_sources:
                raw_items = fetch_rss(source_cfg, max_items=max_items)
                scanned_counts["rss"] += len(raw_items)
                for raw in raw_items:
                    stored = _store_candidate(storage, raw, source_cfg, "rss")
                    if stored and _is_recent(stored, since_dt):
                        stored["source_quality"] = _quality_for_source(source_cfg, source_quality)
                        stored["source_category"] = source_cfg.get("category", "rss")
                        candidates.append(stored)
            statuses["rss"] = "ok"
        except Exception as exc:
            statuses["rss"] = "warning"
            warnings.append(f"RSS scan warning: {exc}")

    query_plan = _queries_for_scan(watchlist, query, max_queries=max_queries)
    google_cfg = google_news_config or {}
    google_query_limit = min(max_queries, int(google_cfg.get("max_queries_per_topic", 3)))
    google_item_limit = min(max_items, int(google_cfg.get("max_items_per_query", 20)))
    if "google_news_rss" in virtual_sources:
        try:
            for item in query_plan[:google_query_limit]:
                cache_key = f"google_news_rss:{item['query']}"
                payload = None
                cached = storage.get_gdelt_cache(cache_key)
                if cached and _cache_is_fresh(cached.get("fetched_at", ""), int(google_cfg.get("cache_ttl_minutes", 60))):
                    payload = cached.get("payload") or {}
                    statuses["google_news_rss"] = "cache"
                if payload is None:
                    raw_items = _google_news_items(item["query"], max_items=google_item_limit, config=google_cfg)
                    payload = {"articles": raw_items}
                    storage.set_gdelt_cache(cache_key, utc_now_iso(), payload)
                    if statuses.get("google_news_rss") != "cache":
                        statuses["google_news_rss"] = "ok"
                raw_items = payload.get("articles") or []
                scanned_counts["google_news_rss"] += len(raw_items)
                for raw in raw_items:
                    source_cfg = _source_cfg_for_article(raw, raw.get("source") or "Google News RSS", "public_metadata")
                    stored = _store_candidate(storage, raw, source_cfg, "google_news_rss", item["query"])
                    if stored and _is_recent(stored, since_dt):
                        stored["source_quality"] = (source_quality or {}).get("google_news_rss", "medium")
                        stored["source_category"] = "google_news_rss"
                        candidates.append(stored)
            if statuses["google_news_rss"] == "pending":
                statuses["google_news_rss"] = "ok"
        except Exception as exc:
            statuses["google_news_rss"] = "warning"
            warnings.append(f"Google News RSS scan warning: {exc}")

    if "gdelt" in virtual_sources:
        cfg = gdelt_config or {}
        ttl_minutes = int(cfg.get("cache_ttl_minutes", 180))
        try:
            for idx, item in enumerate(query_plan[:max_queries]):
                payload = None
                cached = storage.get_gdelt_cache(item["query"])
                if use_cache_first and cached:
                    fetched_at = cached.get("fetched_at", "")
                    try:
                        fetched = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
                        if fetched.tzinfo is None:
                            fetched = fetched.replace(tzinfo=timezone.utc)
                        if datetime.now(timezone.utc) - fetched.astimezone(timezone.utc) <= timedelta(minutes=ttl_minutes):
                            payload = cached.get("payload")
                            statuses["gdelt"] = "cache"
                    except Exception:
                        payload = None
                if payload is None:
                    payload, warning = fetch_gdelt_query(
                        item["query"],
                        max_items=min(max_items, int(cfg.get("max_items_per_query", 10))),
                        timeout=int(cfg.get("timeout_seconds", 20)),
                        max_retries=int(cfg.get("retry_count", 1)),
                        retry_wait_seconds=int(cfg.get("backoff_seconds", 30)),
                        label=f"scan query '{item['query']}'",
                    )
                    if warning:
                        warnings.append(warning)
                        statuses["gdelt"] = "rate-limited" if "429" in warning else "warning"
                        if "429" in warning:
                            break
                        continue
                    storage.set_gdelt_cache(item["query"], utc_now_iso(), payload)
                    if statuses.get("gdelt") != "cache":
                        statuses["gdelt"] = "ok"
                raw_items = _gdelt_items(payload or {})
                scanned_counts["gdelt"] += len(raw_items)
                for raw in raw_items:
                    source_cfg = _source_cfg_for_article(raw, raw.get("source") or "GDELT", raw.get("access_mode") or "public_metadata")
                    stored = _store_candidate(storage, raw, source_cfg, "gdelt", item["query"])
                    if stored and _is_recent(stored, since_dt):
                        stored["source_quality"] = (source_quality or {}).get("gdelt", "medium")
                        stored["source_category"] = "gdelt"
                        candidates.append(stored)
                if idx < max_queries - 1 and int(cfg.get("min_delay_between_queries_seconds", 0)) > 0:
                    # scan defaults to conservative single-query use; multi-query pacing is handled by collect.
                    pass
            if statuses["gdelt"] == "pending":
                statuses["gdelt"] = "ok"
        except Exception as exc:
            statuses["gdelt"] = "warning"
            warnings.append(f"GDELT scan warning: {exc}")

    candidates = _dedupe_candidates(candidates)
    seen_ids = storage.scan_seen_ids(key)
    signals: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    rejected_total = 0
    reject_reason_counts: Dict[str, int] = {}
    threshold = MIN_CONFIDENCE_RANK.get(min_confidence, 1)
    for candidate in candidates:
        if watchlist and all_watchlists:
            signal = classify_across_watchlists(
                candidate,
                all_watchlists,
                current_watchlist=watchlist,
                demote_non_primary=not group_by_primary,
            )
        else:
            signal = classify_signal(candidate, watchlist=watchlist, query=query)
            if watchlist:
                signal.setdefault("primary_topic", topic_name)
                signal.setdefault("secondary_topics", [])
                signal.setdefault("spillover_topics", _spillover_labels(candidate))
        candidate.update(signal)
        candidate["signal_rank"] = SIGNAL_RANK.get(candidate.get("signal_class"), 0)
        if candidate["signal_rank"] <= 0:
            if candidate.get("reject_reason") or show_rejected:
                rejected_total += 1
                reason = str(candidate.get("reject_reason") or candidate.get("why") or "Rejected")
                reject_reason_counts[reason] = reject_reason_counts.get(reason, 0) + 1
            if show_rejected:
                rejected.append(candidate)
            continue
        if primary_only and watchlist and candidate.get("primary_topic") != topic_name:
            candidate["signal_class"] = "noise"
            candidate["signal_rank"] = 0
            candidate["rejection_kind"] = "Demoted"
            candidate["reject_reason"] = f"Primary topic is {candidate.get('primary_topic')}; not shown under {topic_name} in primary-only mode."
            rejected_total += 1
            reject_reason_counts[candidate["reject_reason"]] = reject_reason_counts.get(candidate["reject_reason"], 0) + 1
            if show_rejected:
                rejected.append(candidate)
            continue
        if candidate["signal_rank"] < threshold:
            rejected_total += 1
            reason = f"Below minimum confidence threshold: {candidate.get('signal_class')} < {min_confidence}."
            reject_reason_counts[reason] = reject_reason_counts.get(reason, 0) + 1
            if show_rejected:
                candidate["rejection_kind"] = "Demoted"
                candidate["reject_reason"] = reason
                rejected.append(candidate)
            continue
        if only_new and not show_seen and candidate.get("id") in seen_ids:
            continue
        signals.append(candidate)

    signals.sort(
        key=lambda item: (
            item.get("signal_rank", 0),
            len(item.get("matched_terms") or []),
            item.get("published_at", ""),
        ),
        reverse=True,
    )
    selected = signals[:max_items]
    storage.mark_scan_seen(key, [item.get("id", "") for item in selected])
    selected_high = [item for item in selected if item.get("signal_class") == "high_signal"]

    broad_warning = None
    if query:
        q_terms = [t.lower() for t in query.split() if t]
        if len(q_terms) <= 1 or all(t in GENERIC_CONTEXT_TERMS for t in q_terms):
            broad_warning = "Free-form query may be too broad; use context plus concrete event terms."
            warnings.append(broad_warning)

    return {
        "topic": topic_name,
        "query": query,
        "since": since_label,
        "sources": source_list,
        "source_groups_used": source_list,
        "default_sources_used": default_sources_used,
        "source_status": statuses,
        "warnings": warnings,
        "scanned_counts": scanned_counts,
        "new_items_scanned": len(candidates),
        "signals": selected,
        "rejected": rejected[:max_items],
        "rejected_count": rejected_total,
        "reject_reason_counts": reject_reason_counts,
        "source_diversity_note": source_diversity_note(topic_name, selected_high),
        "seen_hidden": max(0, len(signals) - len(selected)),
    }


def render_scan_markdown(result: Dict[str, Any]) -> str:
    subject = result.get("topic") or result.get("query") or "scan"
    sources = ",".join(result.get("sources") or [])
    signals = result.get("signals") or []
    rejected = result.get("rejected") or []
    high = [s for s in signals if s.get("signal_class") == "high_signal"]
    medium = [s for s in signals if s.get("signal_class") == "medium_signal"]
    low = [s for s in signals if s.get("signal_class") == "low_signal"]

    lines = [
        f"# Signal Scan: {subject}",
        f"Window: last {result.get('since')}",
        f"Sources: {sources}",
        f"New items scanned: {result.get('new_items_scanned', 0)}",
        f"Signals found: {len(signals)}",
    ]
    _append_fresh_ingest(lines, result)
    if result.get("source_groups_used"):
        lines.extend(["", "## Source Groups Used"])
        for group in result.get("source_groups_used") or []:
            lines.append(f"- {group}")
    if not high and not medium:
        lines.extend(
            [
                "",
                f"No high or medium signals found in the last {result.get('since')}.",
                "Scanned:",
                f"- RSS items: {result.get('scanned_counts', {}).get('rss', 0)}",
                f"- GDELT items: {result.get('scanned_counts', {}).get('gdelt', 0)}",
                f"- Google News RSS items: {result.get('scanned_counts', {}).get('google_news_rss', 0)}",
                f"- New items: {result.get('new_items_scanned', 0)}",
            ]
        )

    def section(title: str, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        lines.extend(["", f"## {title}"])
        for idx, row in enumerate(rows, start=1):
            matched = ", ".join(row.get("matched_terms") or []) or "-"
            missing = ", ".join(row.get("missing_required_terms") or []) or "-"
            secondary = ", ".join(row.get("secondary_topics") or []) or "-"
            lines.append(f"{idx}. {_headline_link(row)}")
            lines.append(f"   Source: {row.get('source', '-')}")
            lines.append(f"   Time: {row.get('published_at', '-')}")
            lines.append(f"   Primary topic: {row.get('primary_topic') or result.get('topic') or 'free_form_query'}")
            lines.append(f"   Secondary topics: {secondary}")
            lines.append(f"   Signal: {row.get('signal_class')}")
            lines.append(f"   Source quality: {row.get('source_quality', '-')}")
            lines.append(f"   Matched terms: {matched}")
            if missing != "-":
                lines.append(f"   Missing required terms: {missing}")
            lines.append(f"   Why it matters: {row.get('why', '-')}")

    section("High Signal", high)
    section("Medium Signal", medium)
    section("Low Signal", low)

    if rejected:
        lines.extend(["", "## Rejected / Demoted"])
        for row in rejected:
            matched = ", ".join(row.get("matched_terms") or []) or "-"
            missing = ", ".join(row.get("missing_required_terms") or []) or "-"
            lines.append(f"- {_headline_link(row)}")
            lines.append(f"  {row.get('rejection_kind', 'Rejected')} from: {result.get('topic') or row.get('primary_topic') or subject}")
            lines.append(f"  Reason: {row.get('reject_reason') or row.get('why') or '-'}")
            lines.append(f"  Matched terms: {matched}")
            if missing != "-":
                lines.append(f"  Missing required terms: {missing}")

    summary = result.get("watchlist_summary") or []
    if not summary and result.get("topic"):
        status = "HIGH ALERT" if high else "Active" if medium else "Quiet" if low else "No direct signals"
        if rejected and not signals:
            status = "No direct signals"
        summary = [
            {
                "watchlist": result.get("topic"),
                "high": len(high),
                "medium": len(medium),
                "low": len(low),
                "rejected": result.get("rejected_count", len(rejected)),
                "status": status,
            }
        ]
    if summary:
        lines.extend(["", "## Watchlist Summary", "| Watchlist | High | Medium | Low | Rejected | Status |", "|---|---:|---:|---:|---:|---|"])
        for row in summary:
            lines.append(
                f"| {row.get('watchlist')} | {row.get('high', 0)} | {row.get('medium', 0)} | {row.get('low', 0)} | {row.get('rejected', 0)} | {row.get('status', '-')} |"
            )

    source_note = result.get("source_diversity_note")
    if source_note:
        lines.extend(["", "## Source Diversity", f"- {source_note}"])

    lines.extend(["", "## Source Status"])
    for name, status in (result.get("source_status") or {}).items():
        label = "GDELT" if name == "gdelt" else "RSS" if name == "rss" else "Google News RSS" if name == "google_news_rss" else "Fundus"
        lines.append(f"- {label}: {status}")
    if result.get("warnings"):
        lines.extend(["", "## Source Limits"])
        for warning in result["warnings"]:
            lines.append(f"- {warning}")
    lines.extend(["", "## Gaps"])
    if not high:
        lines.append("- No high-confidence headline signal found in this window.")
    if not medium:
        lines.append("- No medium-confidence headline signal found in this window.")
    if not signals:
        lines.append("- Try a longer window or add `--source rss,google_news_rss` for broader headline discovery.")
    return "\n".join(lines)


def _headline_link(row: Dict[str, Any]) -> str:
    title = str(row.get("title") or "Untitled")
    url = str(row.get("url") or "").strip()
    if url:
        return f"[{title}]({url})"
    return f"{title} (URL: unavailable)"


def _append_fresh_ingest(lines: List[str], result: Dict[str, Any]) -> None:
    fresh = result.get("fresh_ingest")
    if not fresh:
        return
    warnings = fresh.get("warnings") or []
    lines.extend(
        [
            "",
            "## Fresh Ingest",
            "- Fresh ingest: ran",
            f"- RSS items inserted: {fresh.get('inserted', 0)}",
            f"- RSS items skipped: {fresh.get('skipped', 0)}",
            f"- RSS warnings: {len(warnings)}",
        ]
    )
    for warning in warnings[:5]:
        lines.append(f"- RSS warning detail: {warning}")


def _cluster_title(row: Dict[str, Any]) -> str:
    fields = _article_fields(row)
    primary = row.get("primary_topic")
    if primary == "iran_war_risk" and match_terms_in_fields(fields, ["Iran", "Tehran", "IRGC"]) and match_terms_in_fields(fields, IRAN_ESCALATION_TERMS):
        return "US-Iran military escalation"
    if match_terms_in_fields(fields, ["Iran", "Hormuz", "Strait of Hormuz"]) and match_terms_in_fields(fields, ["oil", "oil prices", "shipping", "inflation", "rates"]):
        return "Iran oil / Hormuz market spillover"
    if primary == "migration_policy_europe" and match_terms_in_fields(fields, ["migration", "asylum", "return hubs", "deportation", "border controls"]):
        return "EU migration policy"
    if primary == "europe_ru_war_preparations" and match_terms_in_fields(fields, ["procurement", "air defense", "ammunition", "defense budget", "troop deployment", "readiness"]):
        return "European defense readiness and procurement"
    words = [
        w
        for w in re.findall(r"[a-z0-9]+", str(row.get("title") or "").lower())
        if w not in {"the", "and", "for", "with", "from", "that", "this", "after", "amid"}
    ]
    return " ".join(words[:6]).title() or str(primary or "Headline cluster")


def build_signal_clusters(signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for row in signals:
        grouped.setdefault((str(row.get("primary_topic") or "unassigned"), _cluster_title(row)), []).append(row)

    clusters: List[Dict[str, Any]] = []
    for (topic, title), rows in grouped.items():
        rows_sorted = sorted(rows, key=lambda item: str(item.get("published_at") or ""), reverse=True)
        families = {_source_family(str(row.get("source") or "")) for row in rows_sorted}
        signal_level = max((row.get("signal_class") or "noise" for row in rows_sorted), key=lambda value: SIGNAL_RANK.get(value, 0))
        spillovers = sorted({label for row in rows_sorted for label in (row.get("spillover_topics") or [])})
        latest = rows_sorted[0].get("published_at", "-") if rows_sorted else "-"
        clusters.append(
            {
                "title": title,
                "primary_topic": topic,
                "signal_level": signal_level,
                "source_count": len(families),
                "headline_count": len(rows_sorted),
                "latest_time": latest,
                "key_headlines": rows_sorted[:3],
                "source_diversity": "confirmed cluster" if len(families) >= 2 else "limited source diversity",
                "spillovers": spillovers,
            }
        )
    clusters.sort(
        key=lambda item: (
            SIGNAL_RANK.get(item.get("signal_level"), 0),
            int(item.get("headline_count") or 0),
            str(item.get("latest_time") or ""),
        ),
        reverse=True,
    )
    return clusters


def render_all_watchlists_scan_markdown(result: Dict[str, Any]) -> str:
    signals = result.get("signals") or []
    rejected = result.get("rejected") or []
    clusters = build_signal_clusters(signals)
    lines = [
        f"# Watchlist Signal Scan - Last {result.get('since')}",
        f"Window: last {result.get('since')}",
        f"Sources: {','.join(result.get('sources') or [])}",
        f"Items scanned: {result.get('new_items_scanned', 0)}",
        f"Signals found: {len(signals)}",
        f"Clusters found: {len(clusters)}",
    ]
    _append_fresh_ingest(lines, result)
    if clusters:
        lines.extend(["", "## Top Alerts"])
        for cluster in clusters[:5]:
            label = "HIGH" if cluster.get("signal_level") == "high_signal" else "MEDIUM" if cluster.get("signal_level") == "medium_signal" else "LOW"
            lines.append(f"- {label}: {cluster.get('title')}, {cluster.get('headline_count')} headlines, {cluster.get('source_count')} sources")

    diagnostics = result.get("routing_diagnostics") or {}
    if diagnostics:
        lines.extend(
            [
                "",
                "## Routing Diagnostics",
                f"- Total scanned: {diagnostics.get('total_scanned', 0)}",
                f"- Candidate matches before routing: {diagnostics.get('candidate_matches_before_routing', 0)}",
                f"- Shown signals after routing: {diagnostics.get('shown_signals_after_routing', len(signals))}",
                f"- Clusters found: {len(clusters)}",
                f"- Suppressed duplicates: {diagnostics.get('suppressed_duplicates', 0)}",
                f"- Rejected by hard gates: {diagnostics.get('rejected_by_hard_gates', 0)}",
            ]
        )
        top_reasons = diagnostics.get("top_reject_reasons") or []
        if top_reasons:
            lines.append("- Top reject reasons:")
            for reason, count in top_reasons:
                lines.append(f"  - {count}x {reason}")

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in signals:
        grouped.setdefault(row.get("primary_topic") or "unassigned", []).append(row)

    if not grouped:
        lines.extend(["", f"No high or medium signals found in the last {result.get('since')}."])

    if grouped:
        lines.extend(["", "## Watchlist Sections"])
    for topic in sorted(grouped):
        lines.extend(["", f"### {topic}"])
        for cluster in [cluster for cluster in clusters if cluster.get("primary_topic") == topic]:
            lines.extend(["", f"#### Cluster: {cluster.get('title')}"])
            lines.append(f"Signal level: {cluster.get('signal_level')}")
            lines.append(f"Sources: {cluster.get('source_count')}")
            lines.append(f"Headlines: {cluster.get('headline_count')}")
            lines.append(f"Latest: {cluster.get('latest_time')}")
            lines.append(f"Source diversity: {cluster.get('source_diversity')}")
            if cluster.get("spillovers"):
                lines.append(f"Spillover: {', '.join(cluster.get('spillovers') or [])}")
            lines.append("Key headlines:")
            for row in cluster.get("key_headlines") or []:
                lines.append(f"- {_headline_link(row)}")
                matched = ", ".join(row.get("matched_terms") or []) or "-"
                secondary = ", ".join(row.get("secondary_topics") or []) or "-"
                spillover = ", ".join(row.get("spillover_topics") or []) or "-"
                lines.append(f"   Source: {row.get('source', '-')}")
                lines.append(f"   Time: {row.get('published_at', '-')}")
                lines.append(f"   Primary topic: {row.get('primary_topic', '-')}")
                lines.append(f"   Secondary topics: {secondary}")
                lines.append(f"   Spillover topics: {spillover}")
                lines.append(f"   Signal: {row.get('signal_class')}")
                lines.append(f"   Matched terms: {matched}")
                lines.append(f"   Source quality: {row.get('source_quality', '-')}")
                lines.append(f"   Why it matters: {row.get('why', '-')}")

    spillover_rows = [cluster for cluster in clusters if cluster.get("spillovers")]
    if spillover_rows:
        lines.extend(["", "## Market / Energy Spillover"])
        for cluster in spillover_rows:
            lines.append(f"- {cluster.get('title')}: {', '.join(cluster.get('spillovers') or [])}")

    if rejected:
        lines.extend(["", "## Rejected / Demoted"])
        for row in rejected:
            lines.append(f"- {_headline_link(row)}")
            lines.append(f"  Reason: {row.get('reject_reason') or row.get('why') or '-'}")

    summary = result.get("watchlist_summary") or []
    if summary:
        lines.extend(["", "## Watchlist Summary", "| Watchlist | High | Medium | Low | Rejected | Status |", "|---|---:|---:|---:|---:|---|"])
        for row in summary:
            lines.append(
                f"| {row.get('watchlist')} | {row.get('high', 0)} | {row.get('medium', 0)} | {row.get('low', 0)} | {row.get('rejected', 0)} | {row.get('status', '-')} |"
            )

    diversity = result.get("source_diversity_notes") or []
    if diversity:
        lines.extend(["", "## Source Diversity"])
        for note in diversity:
            lines.append(f"- {note}")

    lines.extend(["", "## Source Status"])
    for name, status in (result.get("source_status") or {}).items():
        label = "GDELT" if name == "gdelt" else "RSS" if name == "rss" else "Google News RSS" if name == "google_news_rss" else "Fundus"
        lines.append(f"- {label}: {status}")
    if result.get("warnings"):
        lines.extend(["", "## Source Limits"])
        for warning in result["warnings"]:
            lines.append(f"- {warning}")
    return "\n".join(lines)
