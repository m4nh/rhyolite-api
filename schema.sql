-- Rhyolite Postgres schema (source-of-truth DDL)
-- Requires Postgres. UUIDs are generated via pgcrypto.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Kinds: JSON schema for node payloads
CREATE TABLE IF NOT EXISTS kinds (
	name TEXT PRIMARY KEY,
	schema JSONB NOT NULL
);

-- Nodes
CREATE TABLE IF NOT EXISTS nodes (
	id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
	kind TEXT NOT NULL REFERENCES kinds(name) ON DELETE RESTRICT,
	payload JSONB NOT NULL DEFAULT '{}'::jsonb,
	created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
	updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_nodes_kind ON nodes(kind);

-- Index to accelerate queries over JSONB payload fields
CREATE INDEX IF NOT EXISTS ix_nodes_payload_gin ON nodes USING gin (payload);

-- Auto-update updated_at on node updates
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
	NEW.updated_at = now();
	RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_nodes_set_updated_at ON nodes;
CREATE TRIGGER trg_nodes_set_updated_at
BEFORE UPDATE ON nodes
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

-- Allowed relationships between kinds
CREATE TABLE IF NOT EXISTS edges_kinds (
	from_kind TEXT NOT NULL REFERENCES kinds(name) ON DELETE CASCADE,
	to_kind TEXT NOT NULL REFERENCES kinds(name) ON DELETE CASCADE,
	relation TEXT NOT NULL,
	PRIMARY KEY (from_kind, to_kind, relation)
);

-- Edges between nodes
CREATE TABLE IF NOT EXISTS edges (
	from_id UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
	to_id UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
	relation TEXT NOT NULL,
	created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
	PRIMARY KEY (from_id, to_id, relation)
);

CREATE INDEX IF NOT EXISTS ix_edges_from_id ON edges(from_id);
CREATE INDEX IF NOT EXISTS ix_edges_to_id ON edges(to_id);
CREATE INDEX IF NOT EXISTS ix_edges_from_to ON edges(from_id, to_id);

-- Attachments: files stored in external storage, referenced by file_path
CREATE TABLE IF NOT EXISTS attachments (
	id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
	node_id UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
	mime_type TEXT NOT NULL,
	name TEXT NOT NULL,
	file_path TEXT NOT NULL UNIQUE,
	created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_attachments_node_id ON attachments(node_id);

