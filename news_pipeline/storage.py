from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .normalize import canonicalize_url, title_hash
from .relevance import classify_search_result, match_terms_in_fields, match_terms_in_text

RELEVANCE_ORDER = {
    "direct_match": 3,
    "strong_partial_match": 2,
    "weak_partial_match": 1,
    "no_match": 0,
}


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=30000;")

    def close(self) -> None:
        self.conn.close()

    def init_db(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS sources (
                name TEXT PRIMARY KEY,
                source_type TEXT,
                adapter TEXT,
                url TEXT,
                language TEXT,
                region TEXT,
                access_mode TEXT,
                enabled INTEGER,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS articles (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                canonical_url TEXT NOT NULL,
                published_at TEXT NOT NULL,
                author TEXT,
                language TEXT,
                country TEXT,
                summary TEXT,
                text TEXT,
                topics TEXT,
                keywords_matched TEXT,
                access_mode TEXT,
                created_at TEXT,
                title_hash TEXT NOT NULL,
                inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(canonical_url),
                UNIQUE(title_hash)
            );

            CREATE TABLE IF NOT EXISTS watchlists (
                name TEXT PRIMARY KEY,
                topic TEXT,
                keywords TEXT,
                phrases TEXT,
                sources TEXT,
                date_from TEXT,
                date_to TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS article_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id TEXT NOT NULL,
                watchlist TEXT NOT NULL,
                matched_keywords TEXT,
                matched_phrases TEXT,
                matched_on TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(article_id, watchlist),
                FOREIGN KEY(article_id) REFERENCES articles(id),
                FOREIGN KEY(watchlist) REFERENCES watchlists(name)
            );

            CREATE TABLE IF NOT EXISTS collection_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                source TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                warnings TEXT,
                query_count INTEGER NOT NULL DEFAULT 0,
                inserted_count INTEGER NOT NULL DEFAULT 0,
                updated_count INTEGER NOT NULL DEFAULT 0,
                enriched_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS article_sources_metadata (
                article_id TEXT PRIMARY KEY,
                discovery_source TEXT,
                discovery_query TEXT,
                access_mode TEXT,
                enrichment_status TEXT,
                enrichment_adapter TEXT,
                relevance_class TEXT,
                confidence TEXT,
                reason TEXT,
                matched_context_terms TEXT,
                matched_core_terms TEXT,
                matched_event_triggers TEXT,
                matched_financial_terms TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(article_id) REFERENCES articles(id)
            );

            CREATE TABLE IF NOT EXISTS gdelt_query_cache (
                query TEXT PRIMARY KEY,
                fetched_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scan_seen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_key TEXT NOT NULL,
                article_id TEXT NOT NULL,
                shown_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(scan_key, article_id),
                FOREIGN KEY(article_id) REFERENCES articles(id)
            );
            """
        )
        self._ensure_column("sources", "adapter", "TEXT")
        self._ensure_column("article_sources_metadata", "confidence", "TEXT")
        self._ensure_column("article_sources_metadata", "reason", "TEXT")
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, column_type: str) -> None:
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        names = set()
        for row in rows:
            try:
                names.add(row["name"])
            except Exception:
                if len(row) > 1:
                    names.add(row[1])
        if column not in names:
            try:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise

    def upsert_sources(self, sources: Iterable[Dict[str, Any]]) -> None:
        rows = [
            (
                s.get("name"),
                s.get("type", "news"),
                s.get("adapter", "rss"),
                s.get("url", ""),
                s.get("language", "unknown"),
                s.get("region", "global"),
                s.get("access_mode", "public"),
                1 if s.get("enabled", True) else 0,
                s.get("updated_at", ""),
            )
            for s in sources
        ]
        self.conn.executemany(
            """
            INSERT INTO sources(name, source_type, adapter, url, language, region, access_mode, enabled, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                source_type=excluded.source_type,
                adapter=excluded.adapter,
                url=excluded.url,
                language=excluded.language,
                region=excluded.region,
                access_mode=excluded.access_mode,
                enabled=excluded.enabled,
                updated_at=excluded.updated_at
            """,
            rows,
        )
        self.conn.commit()

    def upsert_watchlists(self, watchlists: Iterable[Dict[str, Any]]) -> None:
        rows = [
            (
                w.get("name"),
                w.get("topic", w.get("name", "")),
                json.dumps(w.get("keywords", []), ensure_ascii=False),
                json.dumps(w.get("phrases", []), ensure_ascii=False),
                json.dumps(w.get("sources", []), ensure_ascii=False),
                w.get("date_from"),
                w.get("date_to"),
            )
            for w in watchlists
        ]
        self.conn.executemany(
            """
            INSERT INTO watchlists(name, topic, keywords, phrases, sources, date_from, date_to)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                topic=excluded.topic,
                keywords=excluded.keywords,
                phrases=excluded.phrases,
                sources=excluded.sources,
                date_from=excluded.date_from,
                date_to=excluded.date_to,
                updated_at=CURRENT_TIMESTAMP
            """,
            rows,
        )
        self.conn.commit()

    def insert_article(self, article: Dict[str, Any]) -> bool:
        canonical_url = canonicalize_url(article.get("url", ""))
        thash = title_hash(article.get("title", ""))

        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO articles(
                id, source, title, url, canonical_url, published_at, author, language, country,
                summary, text, topics, keywords_matched, access_mode, created_at, title_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.get("id"),
                article.get("source"),
                article.get("title"),
                article.get("url"),
                canonical_url,
                article.get("published_at"),
                article.get("author", ""),
                article.get("language", "unknown"),
                article.get("country", ""),
                article.get("summary", ""),
                article.get("text", ""),
                json.dumps(article.get("topics", []), ensure_ascii=False),
                json.dumps(article.get("keywords_matched", []), ensure_ascii=False),
                article.get("access_mode", "public"),
                article.get("created_at"),
                thash,
            ),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def article_id_for(self, url: str, title: str) -> str | None:
        canonical_url = canonicalize_url(url)
        thash = title_hash(title)
        row = self.conn.execute(
            """
            SELECT id
            FROM articles
            WHERE canonical_url = ? OR title_hash = ?
            ORDER BY inserted_at DESC
            LIMIT 1
            """,
            (canonical_url, thash),
        ).fetchone()
        return row["id"] if row else None

    def update_article_text(
        self,
        article_id: str,
        summary: str | None = None,
        text: str | None = None,
        title: str | None = None,
        author: str | None = None,
        published_at: str | None = None,
    ) -> None:
        updates = []
        params: List[Any] = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if author is not None:
            updates.append("author = ?")
            params.append(author)
        if published_at is not None:
            updates.append("published_at = ?")
            params.append(published_at)
        if summary is not None:
            updates.append("summary = ?")
            params.append(summary)
        if text is not None:
            updates.append("text = ?")
            params.append(text)
        if not updates:
            return
        params.append(article_id)
        self.conn.execute(f"UPDATE articles SET {', '.join(updates)} WHERE id = ?", params)
        self.conn.commit()

    def start_collection_run(self, topic: str, source: str, started_at: str) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO collection_runs(topic, source, started_at, status, warnings)
            VALUES (?, ?, ?, ?, ?)
            """,
            (topic, source, started_at, "running", "[]"),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_collection_run(
        self,
        run_id: int,
        finished_at: str,
        status: str,
        warnings: List[str],
        query_count: int,
        inserted_count: int,
        updated_count: int,
        enriched_count: int,
    ) -> None:
        self.conn.execute(
            """
            UPDATE collection_runs
            SET finished_at = ?, status = ?, warnings = ?, query_count = ?,
                inserted_count = ?, updated_count = ?, enriched_count = ?
            WHERE id = ?
            """,
            (
                finished_at,
                status,
                json.dumps(warnings, ensure_ascii=False),
                query_count,
                inserted_count,
                updated_count,
                enriched_count,
                run_id,
            ),
        )
        self.conn.commit()

    def upsert_article_metadata(self, article_id: str, metadata: Dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO article_sources_metadata(
                article_id, discovery_source, discovery_query, access_mode, enrichment_status,
                enrichment_adapter, relevance_class, confidence, reason, matched_context_terms, matched_core_terms,
                matched_event_triggers, matched_financial_terms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_id) DO UPDATE SET
                discovery_source=COALESCE(excluded.discovery_source, discovery_source),
                discovery_query=COALESCE(excluded.discovery_query, discovery_query),
                access_mode=COALESCE(excluded.access_mode, access_mode),
                enrichment_status=COALESCE(excluded.enrichment_status, enrichment_status),
                enrichment_adapter=COALESCE(excluded.enrichment_adapter, enrichment_adapter),
                relevance_class=COALESCE(excluded.relevance_class, relevance_class),
                confidence=COALESCE(excluded.confidence, confidence),
                reason=COALESCE(excluded.reason, reason),
                matched_context_terms=COALESCE(excluded.matched_context_terms, matched_context_terms),
                matched_core_terms=COALESCE(excluded.matched_core_terms, matched_core_terms),
                matched_event_triggers=COALESCE(excluded.matched_event_triggers, matched_event_triggers),
                matched_financial_terms=COALESCE(excluded.matched_financial_terms, matched_financial_terms),
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                article_id,
                metadata.get("discovery_source"),
                metadata.get("discovery_query"),
                metadata.get("access_mode"),
                metadata.get("enrichment_status"),
                metadata.get("enrichment_adapter"),
                metadata.get("relevance_class"),
                metadata.get("confidence"),
                metadata.get("reason"),
                json.dumps(metadata.get("matched_context_terms", []), ensure_ascii=False),
                json.dumps(metadata.get("matched_core_terms", []), ensure_ascii=False),
                json.dumps(metadata.get("matched_event_triggers", []), ensure_ascii=False),
                json.dumps(metadata.get("matched_financial_terms", []), ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def get_gdelt_cache(self, query: str) -> Dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT fetched_at, payload FROM gdelt_query_cache WHERE query = ?",
            (query,),
        ).fetchone()
        if not row:
            return None
        try:
            return {"fetched_at": row["fetched_at"], "payload": json.loads(row["payload"])}
        except Exception:
            return None

    def set_gdelt_cache(self, query: str, fetched_at: str, payload: Dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO gdelt_query_cache(query, fetched_at, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(query) DO UPDATE SET fetched_at=excluded.fetched_at, payload=excluded.payload
            """,
            (query, fetched_at, json.dumps(payload, ensure_ascii=False)),
        )
        self.conn.commit()

    def list_articles_for_enrichment(self, days: int, topic: str, limit: int) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT a.id, a.source, a.title, a.url, a.published_at, a.summary, a.text, a.access_mode,
                   m.discovery_source, m.discovery_query, m.enrichment_status, m.enrichment_adapter,
                   m.relevance_class, m.confidence, m.reason
            FROM articles a
            JOIN article_sources_metadata m ON m.article_id = a.id
            WHERE a.published_at >= datetime('now', ?)
              AND m.discovery_query IS NOT NULL
              AND (m.enrichment_status IS NULL OR m.enrichment_status IN ('not_attempted', 'failed', 'adapter_unavailable'))
            ORDER BY a.published_at DESC
            LIMIT ?
            """,
            (f"-{int(days)} day", int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]

    def insert_match(self, article_id: str, match: Dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO article_matches(article_id, watchlist, matched_keywords, matched_phrases)
            VALUES (?, ?, ?, ?)
            """,
            (
                article_id,
                match.get("watchlist", "default"),
                json.dumps(match.get("matched_keywords", []), ensure_ascii=False),
                json.dumps(match.get("matched_phrases", []), ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def _tokenize_query(self, query: str) -> List[str]:
        terms = re.findall(r"[a-z0-9]+", (query or "").lower())
        seen = set()
        unique_terms: List[str] = []
        for term in terms:
            if term not in seen:
                unique_terms.append(term)
                seen.add(term)
        return unique_terms

    def _score_row(self, row: Dict[str, Any], terms: List[str], phrase: str) -> tuple[float, List[str]]:
        title = row.get("title") or ""
        summary = row.get("summary") or ""
        text = row.get("text") or ""
        source = row.get("source") or ""
        keywords = row.get("keywords_matched") or ""

        score = 0.0
        matched_terms = match_terms_in_fields([title, summary, text, source, keywords], terms)

        if phrase and match_terms_in_text("\n".join([title, summary, text]), [phrase]):
            score += 8.0

        for term in matched_terms:
            if match_terms_in_text(title, [term]):
                score += 5.0
            if match_terms_in_text(summary, [term]):
                score += 3.0
            if match_terms_in_text(text, [term]):
                score += 2.0
            if match_terms_in_text(source, [term]):
                score += 1.5
            if match_terms_in_text(str(keywords), [term]):
                score += 2.5

        published = row.get("published_at")
        if published:
            try:
                dt = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 86400.0
                score += max(0.0, 5.0 - min(age_days, 20.0) * 0.2)
            except Exception:
                pass

        return score, matched_terms

    def search_articles(
        self,
        query: str,
        source: str | None = None,
        days: int | None = None,
        limit: int = 50,
        min_terms: int | None = None,
    ) -> List[Dict[str, Any]]:
        terms = self._tokenize_query(query)
        phrase = (query or "").strip().lower()
        if not terms and not phrase:
            return []

        params: List[Any] = []
        where: List[str] = []

        if terms:
            term_conditions: List[str] = []
            for term in terms:
                like_q = f"%{term}%"
                term_conditions.append(
                    "(title LIKE ? OR summary LIKE ? OR text LIKE ? OR source LIKE ? OR keywords_matched LIKE ?)"
                )
                params.extend([like_q, like_q, like_q, like_q, like_q])
            where.append("(" + " OR ".join(term_conditions) + ")")

        if source:
            where.append("source = ?")
            params.append(source)

        if days is not None:
            where.append("published_at >= datetime('now', ?)")
            params.append(f"-{int(days)} day")

        sql = """
            SELECT id, source, title, url, published_at, summary, text, keywords_matched, access_mode
            FROM articles
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY published_at DESC LIMIT ?"
        params.append(max(int(limit) * 20, 200))

        rows = [dict(r) for r in self.conn.execute(sql, params).fetchall()]
        scored: List[Dict[str, Any]] = []
        for row in rows:
            score, matched_terms = self._score_row(row, terms, phrase)
            if not matched_terms and not match_terms_in_text(
                " ".join([row.get("title", ""), row.get("summary", ""), row.get("text", "")]),
                [phrase],
            ):
                continue
            matched_terms = sorted(set(matched_terms))
            row["matched_terms"] = matched_terms
            row["missing_terms"] = [term for term in terms if term not in matched_terms]
            row["matched_term_count"] = len(matched_terms)
            row["relevance_class"] = classify_search_result(terms, matched_terms)
            row["relevance_rank"] = RELEVANCE_ORDER.get(row["relevance_class"], 0)
            row["search_score"] = round(score, 3)
            if min_terms is not None and row["matched_term_count"] < int(min_terms):
                continue
            scored.append(row)

        scored.sort(
            key=lambda r: (
                r.get("relevance_rank", 0),
                r.get("matched_term_count", 0),
                r.get("search_score", 0.0),
                r.get("published_at", ""),
            ),
            reverse=True,
        )
        trimmed = scored[: int(limit)]
        for row in trimmed:
            row.pop("text", None)
            row.pop("search_score", None)
            row.pop("relevance_rank", None)
        return trimmed

    def list_recent(self, days: int = 3, source: str | None = None, limit: int = 200) -> List[Dict[str, Any]]:
        params: List[Any] = [f"-{int(days)} day"]
        where = ["a.published_at >= datetime('now', ?)"]

        if source:
            where.append("a.source = ?")
            params.append(source)

        params.append(int(limit))
        sql = f"""
            SELECT a.id, a.source, a.title, a.url, a.published_at, a.summary, a.text, a.keywords_matched,
                   COALESCE(m.access_mode, a.access_mode) AS access_mode,
                   m.discovery_source, m.discovery_query, m.enrichment_status, m.enrichment_adapter,
                   m.relevance_class AS stored_relevance_class, m.confidence AS stored_confidence,
                   m.reason AS stored_reason,
                   m.matched_context_terms, m.matched_core_terms, m.matched_event_triggers,
                   m.matched_financial_terms
            FROM articles a
            LEFT JOIN article_sources_metadata m ON m.article_id = a.id
            WHERE {' AND '.join(where)}
            ORDER BY a.published_at DESC
            LIMIT ?
        """
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def scan_seen_ids(self, scan_key: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT article_id FROM scan_seen WHERE scan_key = ?",
            (scan_key,),
        ).fetchall()
        return {str(row["article_id"]) for row in rows}

    def mark_scan_seen(self, scan_key: str, article_ids: Iterable[str]) -> None:
        rows = [(scan_key, article_id) for article_id in article_ids if article_id]
        if not rows:
            return
        self.conn.executemany(
            """
            INSERT OR IGNORE INTO scan_seen(scan_key, article_id)
            VALUES (?, ?)
            """,
            rows,
        )
        self.conn.commit()

    def latest_collection_run(self, topic: str) -> Dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT topic, source, started_at, finished_at, status, warnings, query_count,
                   inserted_count, updated_count, enriched_count
            FROM collection_runs
            WHERE topic = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (topic,),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["warnings"] = json.loads(data.get("warnings") or "[]")
        except Exception:
            data["warnings"] = []
        return data

    def list_sources(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT name, source_type, adapter, url, language, region, access_mode, enabled
            FROM sources
            ORDER BY enabled DESC, name ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> Dict[str, Any]:
        total_articles = self.conn.execute("SELECT COUNT(*) AS c FROM articles").fetchone()["c"]
        total_sources = self.conn.execute("SELECT COUNT(*) AS c FROM sources WHERE enabled = 1").fetchone()["c"]
        total_matches = self.conn.execute("SELECT COUNT(*) AS c FROM article_matches").fetchone()["c"]
        by_source_rows = self.conn.execute(
            """
            SELECT source, COUNT(*) AS count
            FROM articles
            GROUP BY source
            ORDER BY count DESC, source ASC
            """
        ).fetchall()
        source_by_adapter_rows = self.conn.execute(
            """
            SELECT adapter, COUNT(*) AS count
            FROM sources
            WHERE enabled = 1
            GROUP BY adapter
            ORDER BY count DESC, adapter ASC
            """
        ).fetchall()
        latest_gdelt = self.conn.execute(
            """
            SELECT topic, started_at, finished_at, status, warnings
            FROM collection_runs
            WHERE source LIKE '%gdelt%'
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()
        last_429 = self.conn.execute(
            """
            SELECT finished_at
            FROM collection_runs
            WHERE source LIKE '%gdelt%' AND warnings LIKE '%429%'
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()
        cache_count = self.conn.execute("SELECT COUNT(*) AS c FROM gdelt_query_cache").fetchone()["c"]
        fresh_cache_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM gdelt_query_cache WHERE fetched_at >= datetime('now', '-180 minutes')"
        ).fetchone()["c"]

        return {
            "total_articles": total_articles,
            "enabled_sources": total_sources,
            "total_matches": total_matches,
            "articles_by_source": [dict(r) for r in by_source_rows],
            "enabled_sources_by_adapter": [dict(r) for r in source_by_adapter_rows],
            "gdelt_runtime": {
                "latest_run": dict(latest_gdelt) if latest_gdelt else None,
                "last_429_time": last_429["finished_at"] if last_429 else None,
                "cache_entries": cache_count,
                "fresh_cache_entries": fresh_cache_count,
            },
        }
