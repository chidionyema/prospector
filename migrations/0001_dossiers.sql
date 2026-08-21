-- The dossiers table, in Postgres.
--
-- WHY THIS IS A TRANSCRIPTION AND NOT A DESIGN. Week 1-2 of
-- docs/ENGINE_RUST_REWRITE_SPEC.md is a SHADOW: every write goes to SQLite as it does
-- today AND to Postgres, and nothing reads Postgres. A shadow whose schema "improves" on
-- the original cannot prove anything, because a mismatch is then ambiguous -- was it the
-- dual-write that dropped a row, or the schema that reshaped it? So this file is the live
-- SQLite schema, column for column, in the narrowest Postgres type that holds the same
-- values.
--
-- Taken from the RUNNING database, not from prospector/store.py:
--   sqlite3 /data/store/prospector.db ".schema dossiers"   on prospector-engine, 2026-08-22
-- 22 columns, 10 indexes, 3608 rows.
--
-- THE TYPE MAP, and why each one is the narrowest honest choice:
--
--   TEXT     -> TEXT              same thing.
--   REAL     -> DOUBLE PRECISION  SQLite REAL is an IEEE 754 binary64. So is float8.
--                                 NUMERIC would be wrong: it is exact decimal, so it
--                                 cannot round-trip a binary64 and parity would fail on
--                                 values that are actually identical.
--   INTEGER  -> INTEGER           `provisional` and `retrieval_degraded` are 0/1 flags and
--                                 BOOLEAN is the tempting choice. It is refused here on
--                                 purpose: SQLite will store any integer in that column,
--                                 and a shadow that cannot represent what the source
--                                 actually holds hides the defect instead of finding it.
--                                 Narrow it after parity is green, not before.
--
-- NOT NULL is deliberately absent everywhere except the key. The live table declares none,
-- and adding one here would make the shadow reject a row the source accepted.

CREATE TABLE IF NOT EXISTS dossiers (
    candidate_id            TEXT PRIMARY KEY,
    title                   TEXT,
    one_liner               TEXT,
    decision                TEXT,
    gate_fired              TEXT,
    composite               DOUBLE PRECISION,
    created_at              TEXT,
    reverify_due_at         TEXT,
    path                    TEXT,
    ambition_tier           TEXT,
    structural_form         TEXT,
    provisional             INTEGER DEFAULT 0,
    dense_reward            DOUBLE PRECISION,
    adversarial_confidence  DOUBLE PRECISION,
    persona                 TEXT,
    retrieval_degraded      INTEGER DEFAULT 0,
    market                  TEXT,
    audience                TEXT,
    seed_kind               TEXT,
    lease_owner             TEXT,
    lease_until             DOUBLE PRECISION,
    tombstone               TEXT
);

-- The same ten indexes the live database has, same columns, same order. `created_at` and
-- `path` are unindexed there, so they are unindexed here.
CREATE INDEX IF NOT EXISTS idx_decision        ON dossiers(decision);
CREATE INDEX IF NOT EXISTS idx_reverify        ON dossiers(reverify_due_at);
CREATE INDEX IF NOT EXISTS idx_ambition_tier   ON dossiers(ambition_tier);
CREATE INDEX IF NOT EXISTS idx_structural_form ON dossiers(structural_form);
CREATE INDEX IF NOT EXISTS idx_dense_reward    ON dossiers(dense_reward);
CREATE INDEX IF NOT EXISTS idx_persona         ON dossiers(persona);
CREATE INDEX IF NOT EXISTS idx_market          ON dossiers(market);
CREATE INDEX IF NOT EXISTS idx_audience        ON dossiers(audience);
CREATE INDEX IF NOT EXISTS idx_seed_kind       ON dossiers(seed_kind);
CREATE INDEX IF NOT EXISTS idx_lease_until     ON dossiers(lease_until);
