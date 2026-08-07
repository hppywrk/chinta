-- Chinta Platform — M1 schema (single-user, no multitenancy)

CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    sub         VARCHAR(255) UNIQUE NOT NULL,   -- OIDC subject identifier
    email       VARCHAR(255) UNIQUE,
    name        VARCHAR(255),
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notes (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       VARCHAR(500) NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tags (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS note_tags (
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (note_id, tag_id)
);

CREATE INDEX idx_notes_user_id    ON notes(user_id);
CREATE INDEX idx_notes_created_at ON notes(created_at);
CREATE INDEX idx_note_tags_tag_id ON note_tags(tag_id);

-- Seed a default user for M1 (single-user mode)
INSERT INTO users (sub, email, name)
VALUES ('default', 'dev@localhost', 'Developer')
ON CONFLICT (sub) DO NOTHING;
