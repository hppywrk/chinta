-- Minimal platform tables for v1 admin (subset of docs/CONTROL_PLANE_DDL_V1.sql).
-- Apply before using chinta-platform mutating APIs.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS platform;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tenant_status') THEN
        CREATE TYPE platform.tenant_status AS ENUM (
            'TRIAL_SHARED',
            'ACTIVE_SHARED',
            'MIGRATING_TO_DEDICATED',
            'ACTIVE_DEDICATED',
            'PAST_DUE',
            'SUSPENDED',
            'DEPROVISIONED'
        );
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'runtime_target_type') THEN
        CREATE TYPE platform.runtime_target_type AS ENUM ('SHARED', 'DEDICATED');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS platform.tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    status platform.tenant_status NOT NULL DEFAULT 'ACTIVE_SHARED',
    current_target_type platform.runtime_target_type NOT NULL DEFAULT 'SHARED',
    schema_name TEXT NOT NULL UNIQUE,
    platform_trial_starts_at TIMESTAMPTZ,
    platform_trial_ends_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT tenants_slug_format_chk CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
    CONSTRAINT tenants_schema_format_chk CHECK (schema_name ~ '^t_[a-z0-9_]+$')
);

CREATE INDEX IF NOT EXISTS tenants_status_idx ON platform.tenants(status);

CREATE TABLE IF NOT EXISTS platform.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_subject TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform.memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES platform.tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES platform.users(id) ON DELETE CASCADE,
    role_code TEXT NOT NULL,
    membership_status TEXT NOT NULL DEFAULT 'ACTIVE',
    joined_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, user_id),
    CONSTRAINT memberships_role_chk CHECK (role_code IN ('owner', 'admin', 'member', 'viewer')),
    CONSTRAINT memberships_status_chk CHECK (membership_status IN ('INVITED', 'ACTIVE', 'SUSPENDED', 'REMOVED'))
);

CREATE INDEX IF NOT EXISTS memberships_user_idx ON platform.memberships(user_id);
CREATE INDEX IF NOT EXISTS memberships_tenant_idx ON platform.memberships(tenant_id);
