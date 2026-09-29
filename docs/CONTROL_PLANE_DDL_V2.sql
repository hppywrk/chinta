-- Control Plane DDL v2 (delta on v1)
-- Apply after CONTROL_PLANE_DDL_V1.sql
-- Authz catalog, membership revisions, optional route bindings

BEGIN;

CREATE SCHEMA IF NOT EXISTS authz;

-- Global catalog revision (role x feature matrix changes)
CREATE TABLE IF NOT EXISTS authz.catalog_revision (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    revision BIGINT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO authz.catalog_revision (id, revision)
VALUES (1, 1)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS authz.features (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    module_code TEXT NOT NULL,
    feature_code TEXT NOT NULL,
    display_name TEXT NOT NULL,
    operation_class TEXT NOT NULL DEFAULT 'read', -- read | write | admin
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (module_code, feature_code),
    CONSTRAINT features_module_chk CHECK (module_code ~ '^[a-z][a-z0-9_]*$'),
    CONSTRAINT features_code_chk CHECK (feature_code ~ '^[a-z][a-z0-9_.]*$'),
    CONSTRAINT features_operation_class_chk CHECK (operation_class IN ('read', 'write', 'admin'))
);

CREATE INDEX IF NOT EXISTS features_module_idx ON authz.features(module_code);

-- Grants matrix: role x module x feature
CREATE TABLE IF NOT EXISTS authz.role_feature_grants (
    role_code TEXT NOT NULL,
    module_code TEXT NOT NULL,
    feature_code TEXT NOT NULL,
    effect TEXT NOT NULL DEFAULT 'ALLOW', -- ALLOW | DENY (DENY wins in evaluation)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (role_code, module_code, feature_code),
    CONSTRAINT role_feature_grants_role_chk CHECK (
        role_code IN ('owner', 'admin', 'member', 'viewer')
    ),
    CONSTRAINT role_feature_grants_effect_chk CHECK (effect IN ('ALLOW', 'DENY')),
    CONSTRAINT role_feature_grants_module_chk CHECK (module_code ~ '^[a-z][a-z0-9_]*$'),
    CONSTRAINT role_feature_grants_feature_chk CHECK (feature_code ~ '^[a-z][a-z0-9_.]*$')
);

-- Per (tenant, user) revision for cache invalidation
CREATE TABLE IF NOT EXISTS platform.membership_revisions (
    tenant_id UUID NOT NULL REFERENCES platform.tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES platform.users(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);

-- Optional: persist gateway route bindings (v2 backlog may start with YAML only)
CREATE TABLE IF NOT EXISTS authz.route_bindings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    http_method TEXT NOT NULL,
    path_template TEXT NOT NULL,
    module_code TEXT NOT NULL,
    feature_code TEXT NOT NULL,
    min_role_code TEXT NOT NULL,
    operation_class TEXT NOT NULL DEFAULT 'read',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (http_method, path_template),
    CONSTRAINT route_bindings_method_chk CHECK (http_method IN (
        'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'
    )),
    CONSTRAINT route_bindings_min_role_chk CHECK (
        min_role_code IN ('owner', 'admin', 'member', 'viewer')
    ),
    CONSTRAINT route_bindings_operation_class_chk CHECK (
        operation_class IN ('read', 'write', 'admin')
    )
);

-- Bump helper: call from membership upsert trigger or application layer
CREATE OR REPLACE FUNCTION platform.bump_membership_revision(
    p_tenant_id UUID,
    p_user_id UUID
) RETURNS BIGINT AS $$
DECLARE
    v_rev BIGINT;
BEGIN
    INSERT INTO platform.membership_revisions (tenant_id, user_id, revision)
    VALUES (p_tenant_id, p_user_id, 1)
    ON CONFLICT (tenant_id, user_id)
    DO UPDATE SET
        revision = platform.membership_revisions.revision + 1,
        updated_at = now()
    RETURNING revision INTO v_rev;
    RETURN v_rev;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION authz.bump_catalog_revision() RETURNS BIGINT AS $$
DECLARE
    v_rev BIGINT;
BEGIN
    UPDATE authz.catalog_revision
    SET revision = revision + 1, updated_at = now()
    WHERE id = 1
    RETURNING revision INTO v_rev;
    RETURN v_rev;
END;
$$ LANGUAGE plpgsql;

COMMIT;
