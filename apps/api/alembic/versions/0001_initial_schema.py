"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Extensions ──────────────────────────────────────────────────────────
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    # ── updated_at trigger function ──────────────────────────────────────────
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))

    # ── users ────────────────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE users (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email               TEXT UNIQUE NOT NULL,
            hashed_password     TEXT NOT NULL,
            full_name           TEXT NOT NULL,
            role                TEXT NOT NULL DEFAULT 'other'
                                    CHECK (role IN ('captain', 'mate', 'engineer', 'other')),
            subscription_tier   TEXT NOT NULL DEFAULT 'free'
                                    CHECK (subscription_tier IN ('free', 'solo', 'fleet', 'enterprise')),
            subscription_status TEXT NOT NULL DEFAULT 'active'
                                    CHECK (subscription_status IN ('active', 'inactive', 'past_due', 'canceled')),
            stripe_customer_id  TEXT UNIQUE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    op.execute(sa.text("""
        CREATE TRIGGER users_updated_at
            BEFORE UPDATE ON users
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """))

    # ── refresh_tokens ───────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE refresh_tokens (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash  TEXT NOT NULL UNIQUE,
            expires_at  TIMESTAMPTZ NOT NULL,
            revoked     BOOLEAN NOT NULL DEFAULT FALSE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    # ── vessels ──────────────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE vessels (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name          TEXT NOT NULL,
            vessel_type   TEXT NOT NULL,
            gross_tonnage NUMERIC(12, 2),
            flag_state    TEXT NOT NULL,
            route_type    TEXT NOT NULL
                              CHECK (route_type IN ('inland', 'coastal', 'international')),
            cargo_types   TEXT[] NOT NULL DEFAULT '{}',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    op.execute(sa.text("""
        CREATE TRIGGER vessels_updated_at
            BEFORE UPDATE ON vessels
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """))

    # ── regulations ──────────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE regulations (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source            TEXT NOT NULL
                                  CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'solas', 'marpol', 'stcw', 'mlc')),
            source_version    TEXT,
            title             TEXT NOT NULL,
            section_number    TEXT,
            section_title     TEXT,
            full_text         TEXT,
            chunk_index       INTEGER NOT NULL DEFAULT 0,
            parent_section_id UUID REFERENCES regulations(id) ON DELETE SET NULL,
            effective_date    DATE,
            up_to_date_as_of  DATE,
            embedding         vector(1536),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    # ── conversations ─────────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE conversations (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            vessel_id       UUID REFERENCES vessels(id) ON DELETE SET NULL,
            title           TEXT,
            session_summary TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    op.execute(sa.text("""
        CREATE TRIGGER conversations_updated_at
            BEFORE UPDATE ON conversations
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """))

    # ── messages ─────────────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE messages (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id      UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role                 TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content              TEXT NOT NULL,
            model_used           TEXT CHECK (model_used IN ('haiku', 'sonnet', 'opus')),
            tokens_used          INTEGER,
            cited_regulation_ids UUID[] NOT NULL DEFAULT '{}',
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    # ── regulation_versions ──────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE regulation_versions (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source           TEXT NOT NULL,
            previous_version TEXT,
            new_version      TEXT NOT NULL,
            changed_sections TEXT[] NOT NULL DEFAULT '{}',
            detected_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            applied_at       TIMESTAMPTZ
        )
    """))

    # ── Indexes ───────────────────────────────────────────────────────────────

    # users
    op.execute(sa.text("CREATE INDEX idx_users_created_at ON users(created_at)"))

    # refresh_tokens
    op.execute(sa.text("CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens(user_id)"))
    op.execute(sa.text(
        "CREATE INDEX idx_refresh_tokens_expires_at ON refresh_tokens(expires_at) WHERE NOT revoked"
    ))

    # vessels
    op.execute(sa.text("CREATE INDEX idx_vessels_user_id ON vessels(user_id)"))

    # regulations — composite + self-ref + HNSW
    op.execute(sa.text(
        "CREATE INDEX idx_regulations_source_section ON regulations(source, section_number)"
    ))
    op.execute(sa.text(
        "CREATE INDEX idx_regulations_parent ON regulations(parent_section_id) "
        "WHERE parent_section_id IS NOT NULL"
    ))
    op.execute(sa.text(
        "CREATE INDEX idx_regulations_embedding ON regulations "
        "USING hnsw (embedding vector_cosine_ops)"
    ))

    # conversations
    op.execute(sa.text(
        "CREATE INDEX idx_conversations_user_id_created ON conversations(user_id, created_at)"
    ))
    op.execute(sa.text(
        "CREATE INDEX idx_conversations_vessel_id ON conversations(vessel_id) "
        "WHERE vessel_id IS NOT NULL"
    ))

    # messages
    op.execute(sa.text(
        "CREATE INDEX idx_messages_conversation_id_created ON messages(conversation_id, created_at)"
    ))

    # regulation_versions
    op.execute(sa.text(
        "CREATE INDEX idx_regulation_versions_source ON regulation_versions(source)"
    ))
    op.execute(sa.text(
        "CREATE INDEX idx_regulation_versions_detected_at ON regulation_versions(detected_at)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS regulation_versions CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS messages CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS conversations CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS regulations CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS vessels CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS refresh_tokens CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS users CASCADE"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS set_updated_at CASCADE"))
