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
            """
        )
        self._ensure_column("sources", "adapter", "TEXT")
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
        where = ["published_at >= datetime('now', ?)"]

        if source:
            where.append("source = ?")
            params.append(source)

        params.append(int(limit))
        sql = f"""
            SELECT id, source, title, url, published_at, summary, text, keywords_matched, access_mode
            FROM articles
            WHERE {' AND '.join(where)}
            ORDER BY published_at DESC
            LIMIT ?
        """
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

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

        return {
            "total_articles": total_articles,
            "enabled_sources": total_sources,
            "total_matches": total_matches,
            "articles_by_source": [dict(r) for r in by_source_rows],
            "enabled_sources_by_adapter": [dict(r) for r in source_by_adapter_rows],
        }
