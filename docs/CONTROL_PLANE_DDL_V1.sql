-- Control plane DDL (v1)
-- Scope:
--   - shared control-plane schemas
--   - tenant registry, routing, memberships
--   - entitlements and trials
--   - billing primitives
--   - tenant schema migration tracking
--
-- Notes:
--   - Tenant runtime/module tables are intentionally excluded; they live in
--     per-tenant schemas (t_<tenant_key>) managed by module migrations.
--   - Use a migration tool (Alembic/Flyway/Liquibase) to apply incrementally.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS platform;
CREATE SCHEMA IF NOT EXISTS entitlements;
CREATE SCHEMA IF NOT EXISTS billing;
CREATE SCHEMA IF NOT EXISTS audit;

-- ---------------------------------------------------------------------------
-- platform
-- ---------------------------------------------------------------------------

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
    status platform.tenant_status NOT NULL DEFAULT 'TRIAL_SHARED',
    current_target_type platform.runtime_target_type NOT NULL DEFAULT 'SHARED',
    schema_name TEXT NOT NULL UNIQUE, -- ex: t_4f9a7c
    platform_trial_starts_at TIMESTAMPTZ,
    platform_trial_ends_at TIMESTAMPTZ,
    billing_account_ref TEXT,
    dedicated_target_id UUID, -- fk added after tenant_runtime_targets exists
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT tenants_slug_format_chk CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
    CONSTRAINT tenants_schema_format_chk CHECK (schema_name ~ '^t_[a-z0-9_]+$'),
    CONSTRAINT tenants_trial_window_chk CHECK (
        platform_trial_ends_at IS NULL
        OR platform_trial_starts_at IS NULL
        OR platform_trial_ends_at > platform_trial_starts_at
    )
);

CREATE INDEX IF NOT EXISTS tenants_status_idx ON platform.tenants(status);

CREATE TABLE IF NOT EXISTS platform.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_subject TEXT NOT NULL UNIQUE, -- subject from OIDC provider
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
    role_code TEXT NOT NULL, -- owner/admin/member/viewer for v1
    membership_status TEXT NOT NULL DEFAULT 'ACTIVE',
    invited_by_user_id UUID REFERENCES platform.users(id),
    joined_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, user_id),
    CONSTRAINT memberships_role_chk CHECK (role_code IN ('owner', 'admin', 'member', 'viewer')),
    CONSTRAINT memberships_status_chk CHECK (membership_status IN ('INVITED', 'ACTIVE', 'SUSPENDED', 'REMOVED'))
);

CREATE INDEX IF NOT EXISTS memberships_user_idx ON platform.memberships(user_id);
CREATE INDEX IF NOT EXISTS memberships_tenant_idx ON platform.memberships(tenant_id);

CREATE TABLE IF NOT EXISTS platform.tenant_runtime_targets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES platform.tenants(id) ON DELETE CASCADE,
    target_type platform.runtime_target_type NOT NULL,
    api_base_url TEXT NOT NULL,
    db_dsn_secret_ref TEXT NOT NULL, -- reference in secret manager, not plaintext DSN
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id)
);

CREATE UNIQUE INDEX IF NOT EXISTS tenant_runtime_one_active_idx
    ON platform.tenant_runtime_targets(tenant_id)
    WHERE is_active = TRUE;

ALTER TABLE platform.tenants
    ADD CONSTRAINT tenants_dedicated_target_fk
    FOREIGN KEY (dedicated_target_id)
    REFERENCES platform.tenant_runtime_targets(id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE IF NOT EXISTS platform.tenant_schema_versions (
    tenant_id UUID NOT NULL REFERENCES platform.tenants(id) ON DELETE CASCADE,
    module_code TEXT NOT NULL,
    schema_name TEXT NOT NULL,
    migration_version TEXT NOT NULL,
    migrated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, module_code)
);

-- ---------------------------------------------------------------------------
-- entitlements
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'subscription_status') THEN
        CREATE TYPE entitlements.subscription_status AS ENUM (
            'TRIALING',
            'ACTIVE',
            'GRACE_PERIOD',
            'PAST_DUE',
            'SUSPENDED',
            'CANCELED'
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS entitlements.modules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    module_code TEXT NOT NULL UNIQUE, -- ex: tasks, notes, search
    display_name TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT modules_code_chk CHECK (module_code ~ '^[a-z][a-z0-9_]*$')
);

CREATE TABLE IF NOT EXISTS entitlements.plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_code TEXT NOT NULL UNIQUE, -- ex: free, pro, enterprise
    display_name TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT plans_code_chk CHECK (plan_code ~ '^[a-z][a-z0-9_]*$')
);

CREATE TABLE IF NOT EXISTS entitlements.plan_modules (
    plan_id UUID NOT NULL REFERENCES entitlements.plans(id) ON DELETE CASCADE,
    module_id UUID NOT NULL REFERENCES entitlements.modules(id) ON DELETE CASCADE,
    included BOOLEAN NOT NULL DEFAULT TRUE,
    limits_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (plan_id, module_id)
);

CREATE TABLE IF NOT EXISTS entitlements.subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES platform.tenants(id) ON DELETE CASCADE,
    plan_id UUID NOT NULL REFERENCES entitlements.plans(id),
    status entitlements.subscription_status NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    source_ref TEXT, -- external subscription id (payment provider)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT subscriptions_period_chk CHECK (period_end > period_start)
);

CREATE INDEX IF NOT EXISTS subscriptions_tenant_status_idx
    ON entitlements.subscriptions(tenant_id, status);

CREATE TABLE IF NOT EXISTS entitlements.module_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES platform.tenants(id) ON DELETE CASCADE,
    module_id UUID NOT NULL REFERENCES entitlements.modules(id) ON DELETE CASCADE,
    status entitlements.subscription_status NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    source_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, module_id),
    CONSTRAINT module_subscriptions_period_chk CHECK (period_end > period_start)
);

CREATE TABLE IF NOT EXISTS entitlements.trials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES platform.tenants(id) ON DELETE CASCADE,
    scope TEXT NOT NULL, -- PLATFORM or MODULE
    module_id UUID REFERENCES entitlements.modules(id),
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT trials_scope_chk CHECK (scope IN ('PLATFORM', 'MODULE')),
    CONSTRAINT trials_status_chk CHECK (status IN ('ACTIVE', 'EXPIRED', 'REVOKED')),
    CONSTRAINT trials_period_chk CHECK (ends_at > starts_at),
    CONSTRAINT trials_scope_module_chk CHECK (
        (scope = 'PLATFORM' AND module_id IS NULL)
        OR (scope = 'MODULE' AND module_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS trials_tenant_scope_idx
    ON entitlements.trials(tenant_id, scope, status, ends_at);

CREATE TABLE IF NOT EXISTS entitlements.entitlement_revisions (
    tenant_id UUID PRIMARY KEY REFERENCES platform.tenants(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- billing
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'invoice_status') THEN
        CREATE TYPE billing.invoice_status AS ENUM (
            'DRAFT',
            'OPEN',
            'PAID',
            'VOID',
            'UNCOLLECTIBLE'
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS billing.invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES platform.tenants(id) ON DELETE CASCADE,
    invoice_number TEXT NOT NULL UNIQUE,
    status billing.invoice_status NOT NULL DEFAULT 'DRAFT',
    currency_code TEXT NOT NULL DEFAULT 'USD',
    subtotal_amount_cents BIGINT NOT NULL DEFAULT 0,
    tax_amount_cents BIGINT NOT NULL DEFAULT 0,
    total_amount_cents BIGINT NOT NULL DEFAULT 0,
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,
    due_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT invoices_currency_chk CHECK (currency_code ~ '^[A-Z]{3}$')
);

CREATE TABLE IF NOT EXISTS billing.invoice_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id UUID NOT NULL REFERENCES billing.invoices(id) ON DELETE CASCADE,
    line_type TEXT NOT NULL, -- PLAN, MODULE, USAGE, CREDIT, TAX
    description TEXT NOT NULL,
    quantity NUMERIC(20, 6) NOT NULL DEFAULT 1,
    unit_amount_cents BIGINT NOT NULL DEFAULT 0,
    line_total_cents BIGINT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT invoice_lines_type_chk CHECK (line_type IN ('PLAN', 'MODULE', 'USAGE', 'CREDIT', 'TAX'))
);

CREATE TABLE IF NOT EXISTS billing.payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES platform.tenants(id) ON DELETE CASCADE,
    invoice_id UUID REFERENCES billing.invoices(id) ON DELETE SET NULL,
    provider_ref TEXT NOT NULL,
    payment_status TEXT NOT NULL, -- PENDING, SUCCEEDED, FAILED, REFUNDED
    amount_cents BIGINT NOT NULL,
    currency_code TEXT NOT NULL DEFAULT 'USD',
    paid_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT payments_status_chk CHECK (payment_status IN ('PENDING', 'SUCCEEDED', 'FAILED', 'REFUNDED')),
    CONSTRAINT payments_currency_chk CHECK (currency_code ~ '^[A-Z]{3}$')
);

CREATE TABLE IF NOT EXISTS billing.usage_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES platform.tenants(id) ON DELETE CASCADE,
    module_code TEXT NOT NULL,
    metric_code TEXT NOT NULL, -- ex: api_calls, storage_mb_hours
    quantity NUMERIC(20, 6) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS usage_events_tenant_time_idx
    ON billing.usage_events(tenant_id, occurred_at);

-- ---------------------------------------------------------------------------
-- audit
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit.events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES platform.tenants(id) ON DELETE SET NULL,
    actor_type TEXT NOT NULL, -- USER, SERVICE, SYSTEM
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    request_id TEXT,
    ip_address INET,
    user_agent TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS audit_events_tenant_time_idx
    ON audit.events(tenant_id, occurred_at);

CREATE INDEX IF NOT EXISTS audit_events_action_idx
    ON audit.events(action, occurred_at DESC);

COMMIT;
