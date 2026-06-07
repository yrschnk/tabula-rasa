"""Канонический стор SQLite: facts + edges + concepts + FTS5. SPEC 5.5."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from tabula.config import CONFIG
from tabula.models import Fact, FactCandidate, Status


def _db_path(namespace: str) -> Path:
    p = CONFIG.db_path.parent / f"{namespace}.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def _conn(namespace: str):
    con = sqlite3.connect(str(_db_path(namespace)))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


DDL = """
CREATE TABLE IF NOT EXISTS facts (
    fact_id       TEXT PRIMARY KEY,
    namespace     TEXT NOT NULL,
    content       TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    concept       TEXT NOT NULL,
    attributed_to TEXT DEFAULT 'user',
    entities      TEXT DEFAULT '[]',
    timestamp     TEXT,
    valid_from    TEXT NOT NULL,
    valid_to      TEXT,
    strength      REAL DEFAULT 1.0,
    reinforce_cnt INTEGER DEFAULT 0,
    source_raw_id TEXT DEFAULT '',
    status        TEXT DEFAULT 'active',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_ns_concept ON facts(namespace, concept);
CREATE INDEX IF NOT EXISTS idx_facts_hash       ON facts(namespace, content_hash);
CREATE INDEX IF NOT EXISTS idx_facts_valid      ON facts(namespace, valid_to);
CREATE INDEX IF NOT EXISTS idx_facts_status     ON facts(namespace, status);

CREATE TABLE IF NOT EXISTS edges (
    namespace   TEXT NOT NULL,
    src_concept TEXT NOT NULL,
    dst_concept TEXT NOT NULL,
    type        TEXT NOT NULL,
    weight      REAL DEFAULT 0.0,
    updated_at  TEXT,
    PRIMARY KEY (namespace, src_concept, dst_concept, type)
);

CREATE TABLE IF NOT EXISTS concepts (
    namespace TEXT NOT NULL,
    name      TEXT NOT NULL,
    aliases   TEXT DEFAULT '[]',
    embedding BLOB,
    PRIMARY KEY (namespace, name)
);

CREATE TABLE IF NOT EXISTS store_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    fact_id UNINDEXED,
    content,
    concept,
    tokenize='unicode61'
);
"""

FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS facts_fts_insert
AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(fact_id, content, concept)
    VALUES (new.fact_id, new.content, new.concept);
END;

CREATE TRIGGER IF NOT EXISTS facts_fts_delete
AFTER UPDATE OF status ON facts
WHEN new.status != 'active' BEGIN
    DELETE FROM facts_fts WHERE fact_id = old.fact_id;
END;
"""


def init_schema(namespace: str = "personal") -> None:
    with _conn(namespace) as con:
        con.executescript(DDL)
        con.executescript(FTS_TRIGGERS)


def reset_store(namespace: str) -> None:
    """Полная очистка namespace — для изоляции бенч-инстансов. SPEC 6."""
    path = _db_path(namespace)
    if path.exists():
        path.unlink()
    init_schema(namespace)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── facts ────────────────────────────────────────────────────────────────────

def add_fact(c: FactCandidate, namespace: str, source_raw_id: str = "") -> str:
    import uuid
    from tabula.dedup import content_hash
    fid = str(uuid.uuid4())
    now = _now()
    with _conn(namespace) as con:
        con.execute(
            """INSERT INTO facts
               (fact_id, namespace, content, content_hash, concept,
                attributed_to, entities, timestamp, valid_from, valid_to,
                strength, reinforce_cnt, source_raw_id, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,NULL,1.0,0,?,'active',?)""",
            (fid, namespace, c.content, content_hash(c.content), c.concept,
             c.attributed_to, json.dumps(c.entities, ensure_ascii=False),
             c.timestamp, now, source_raw_id, now),
        )
    return fid


def reinforce(fact_id: str, namespace: str) -> None:
    with _conn(namespace) as con:
        con.execute(
            """UPDATE facts SET
               strength = MIN(strength + ?, 1.0),
               reinforce_cnt = reinforce_cnt + 1
               WHERE fact_id=?""",
            (CONFIG.reinforce_delta, fact_id),
        )


def supersede(old_fact_id: str, namespace: str) -> None:
    with _conn(namespace) as con:
        con.execute(
            "UPDATE facts SET valid_to=?, status='superseded' WHERE fact_id=?",
            (_now(), old_fact_id),
        )


def archive(fact_id: str, namespace: str) -> None:
    with _conn(namespace) as con:
        con.execute(
            "UPDATE facts SET valid_to=?, status='archived' WHERE fact_id=?",
            (_now(), fact_id),
        )


def get_fact(fact_id: str, namespace: str) -> Fact | None:
    with _conn(namespace) as con:
        row = con.execute("SELECT * FROM facts WHERE fact_id=?", (fact_id,)).fetchone()
    return _row_to_fact(row) if row else None


def find_by_hash(chash: str, namespace: str) -> Fact | None:
    with _conn(namespace) as con:
        row = con.execute(
            "SELECT * FROM facts WHERE namespace=? AND content_hash=? AND status='active'",
            (namespace, chash),
        ).fetchone()
    return _row_to_fact(row) if row else None


def collect_facts(concepts: list[str], namespace: str,
                  as_of: str | None = None) -> list[Fact]:
    if not concepts:
        return []
    ph = ",".join("?" * len(concepts))
    if as_of:
        q = f"""SELECT * FROM facts
                WHERE namespace=? AND concept IN ({ph})
                AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)
                AND status='active' ORDER BY strength DESC"""
        params: list = [namespace, *concepts, as_of, as_of]
    else:
        q = f"""SELECT * FROM facts
                WHERE namespace=? AND concept IN ({ph})
                AND valid_to IS NULL AND status='active'
                ORDER BY strength DESC"""
        params = [namespace, *concepts]
    with _conn(namespace) as con:
        rows = con.execute(q, params).fetchall()
    return [_row_to_fact(r) for r in rows]


def search_fts(query: str, namespace: str, k: int = 10) -> list[tuple[str, float]]:
    """FTS5 поиск с OR по токенам. Возвращает [(concept, score)]."""
    # Преобразуем "слово1 слово2" → "слово1 OR слово2" для мягкого поиска
    tokens = query.strip().split()
    if len(tokens) > 1:
        fts_query = " OR ".join(tokens)
    else:
        fts_query = query.strip()

    try:
        with _conn(namespace) as con:
            rows = con.execute(
                """SELECT f.concept, fts.rank
                   FROM facts_fts fts
                   JOIN facts f ON fts.fact_id = f.fact_id
                   WHERE facts_fts MATCH ?
                   ORDER BY fts.rank LIMIT ?""",
                (fts_query, k),
            ).fetchall()
        return [(r["concept"], -r["rank"]) for r in rows]
    except Exception:
        # Fallback: LIKE если FTS не сработал
        return []


# ─── edges ────────────────────────────────────────────────────────────────────

def upsert_edge(src: str, dst: str, edge_type: str,
                dweight: float, namespace: str) -> None:
    with _conn(namespace) as con:
        con.execute(
            """INSERT INTO edges(namespace, src_concept, dst_concept, type, weight, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(namespace, src_concept, dst_concept, type)
               DO UPDATE SET weight = MIN(weight + excluded.weight, 1.0),
                             updated_at = excluded.updated_at""",
            (namespace, src, dst, edge_type, dweight, _now()),
        )


def get_edges(namespace: str) -> list[dict]:
    with _conn(namespace) as con:
        rows = con.execute(
            "SELECT src_concept, dst_concept, type, weight FROM edges WHERE namespace=?",
            (namespace,),
        ).fetchall()
    return [dict(r) for r in rows]


# ─── concepts ─────────────────────────────────────────────────────────────────

def upsert_concept(name: str, namespace: str,
                   aliases: list[str] | None = None,
                   embedding: bytes | None = None) -> None:
    with _conn(namespace) as con:
        con.execute(
            """INSERT INTO concepts(namespace, name, aliases, embedding)
               VALUES (?,?,?,?)
               ON CONFLICT(namespace, name) DO UPDATE SET
                 aliases = CASE WHEN excluded.aliases != '[]'
                                THEN excluded.aliases ELSE aliases END,
                 embedding = CASE WHEN excluded.embedding IS NOT NULL
                                  THEN excluded.embedding ELSE embedding END""",
            (namespace, name, json.dumps(aliases or [], ensure_ascii=False), embedding),
        )


def get_all_concepts(namespace: str) -> list[dict]:
    with _conn(namespace) as con:
        rows = con.execute(
            "SELECT name, aliases, embedding FROM concepts WHERE namespace=?",
            (namespace,),
        ).fetchall()
    return [{"name": r["name"],
             "aliases": json.loads(r["aliases"]),
             "embedding": r["embedding"]} for r in rows]


# ─── vector index (sqlite-vec) ────────────────────────────────────────────────

def _ensure_vec_table(namespace: str, dim: int) -> None:
    """Создать facts_vec если не существует (или если размерность изменилась)."""
    import sqlite_vec
    with _conn(namespace) as con:
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        # Проверяем сохранённую размерность
        meta = con.execute(
            "SELECT value FROM store_meta WHERE key='vec_dim'"
        ).fetchone()
        if meta and int(meta["value"]) != dim:
            # Размерность сменилась → дроп и пересоздание
            con.execute("DROP TABLE IF EXISTS facts_vec")
        con.executescript(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS facts_vec
            USING vec0(fact_id TEXT PRIMARY KEY, embedding float[{dim}]);
        """)
        con.execute(
            "INSERT OR REPLACE INTO store_meta(key,value) VALUES('vec_dim',?)",
            (str(dim),),
        )


def upsert_vec(fact_id: str, embedding: list[float], namespace: str) -> None:
    """Сохранить/обновить эмбеддинг факта."""
    import struct, sqlite_vec
    dim = len(embedding)
    _ensure_vec_table(namespace, dim)
    blob = struct.pack(f"{dim}f", *embedding)
    with _conn(namespace) as con:
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        con.execute(
            "INSERT OR REPLACE INTO facts_vec(fact_id, embedding) VALUES(?,?)",
            (fact_id, blob),
        )


def vector_knn(query_vec: list[float], namespace: str,
               k: int = 10) -> list[tuple[str, float]]:
    """KNN поиск в facts_vec. Возвращает [(fact_id, distance)]."""
    import struct, sqlite_vec
    dim = len(query_vec)
    _ensure_vec_table(namespace, dim)
    blob = struct.pack(f"{dim}f", *query_vec)
    with _conn(namespace) as con:
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        rows = con.execute(
            """SELECT fact_id, distance FROM facts_vec
               WHERE embedding MATCH ? AND k=?
               ORDER BY distance""",
            (blob, k),
        ).fetchall()
    return [(r["fact_id"], r["distance"]) for r in rows]


def fact_ids_to_concepts(fact_ids: list[str], namespace: str) -> list[tuple[str, float]]:
    """Конвертировать fact_id → concept для vector результатов."""
    if not fact_ids:
        return []
    ph = ",".join("?" * len(fact_ids))
    with _conn(namespace) as con:
        rows = con.execute(
            f"SELECT fact_id, concept FROM facts WHERE fact_id IN ({ph})",
            fact_ids,
        ).fetchall()
    id_to_concept = {r["fact_id"]: r["concept"] for r in rows}
    return [(id_to_concept[fid], score) for fid, score in
            [(fid, 0.0) for fid in fact_ids] if fid in id_to_concept]


# ─── helpers ──────────────────────────────────────────────────────────────────

def _row_to_fact(row: sqlite3.Row) -> Fact:
    return Fact(
        fact_id=row["fact_id"], namespace=row["namespace"],
        content=row["content"], content_hash=row["content_hash"],
        concept=row["concept"], attributed_to=row["attributed_to"],
        entities=json.loads(row["entities"]),
        timestamp=row["timestamp"], valid_from=row["valid_from"],
        valid_to=row["valid_to"], strength=row["strength"],
        reinforce_cnt=row["reinforce_cnt"], source_raw_id=row["source_raw_id"],
        status=row["status"], created_at=row["created_at"],
    )
