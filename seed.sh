#!/usr/bin/env sh
set -eu

if ! command -v psql >/dev/null 2>&1; then
	echo "ERROR: psql not found. Install postgresql client tools (or use seed.Dockerfile image)." >&2
	exit 1
fi

SCHEMA_FILE="${SCHEMA_FILE:-./schema.sql}"

usage() {
	cat >&2 <<'EOF'
Usage: ./seed.sh [--schema PATH]

Seeds a fresh Rhyolite Postgres database using schema.sql.
Refuses to run if the database is not empty (public schema has objects).

Connection configuration (preferred split vars; no DATABASE_URL required):
	- DATABASE_HOST (required if DATABASE_URL not set)
	- DATABASE_PORT (optional, default 5432)
	- DATABASE_USER (or POSTGRES_USER)
	- DATABASE_PASSWORD (or DATABASE_PASS / POSTGRES_PASSWORD)
	- DATABASE_NAME (or POSTGRES_DB)

Optional:
	- DATABASE_URL (if set, used directly by psql)
	- SCHEMA_FILE (default ./schema.sql)
EOF
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--schema)
			shift
			if [ "$#" -eq 0 ]; then
				echo "ERROR: --schema requires a path" >&2
				usage
				exit 2
			fi
			SCHEMA_FILE="$1"
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			echo "ERROR: Unknown argument: $1" >&2
			usage
			exit 2
			;;
	esac
done

if [ ! -f "$SCHEMA_FILE" ]; then
	echo "ERROR: schema file not found: $SCHEMA_FILE" >&2
	exit 1
fi

DB_URL="${DATABASE_URL:-}"

if [ -n "$DB_URL" ]; then
	psql_cmd() {
		psql "$DB_URL" -v ON_ERROR_STOP=1 "$@"
	}
else
	DB_HOST="${DATABASE_HOST:-}"
	DB_PORT="${DATABASE_PORT:-5432}"
	DB_USER="${DATABASE_USER:-${POSTGRES_USER:-}}"
	DB_PASS="${DATABASE_PASSWORD:-${DATABASE_PASS:-${POSTGRES_PASSWORD:-}}}"
	DB_NAME="${DATABASE_NAME:-${POSTGRES_DB:-}}"

	missing=""
	[ -n "$DB_HOST" ] || missing="${missing} DATABASE_HOST"
	[ -n "$DB_USER" ] || missing="${missing} DATABASE_USER"
	[ -n "$DB_PASS" ] || missing="${missing} DATABASE_PASSWORD"
	[ -n "$DB_NAME" ] || missing="${missing} DATABASE_NAME"
	if [ -n "$missing" ]; then
		echo "ERROR: Missing required env vars:${missing}" >&2
		echo "Set DATABASE_URL instead, or provide the split DATABASE_* variables (see Dockerfile)." >&2
		exit 1
	fi

    # print the database connection info for debugging
    echo "Database connection info:"
    echo "  Host: $DB_HOST"
    echo "  Port: $DB_PORT"
    echo "  User: $DB_USER"
    echo "  Name: $DB_NAME"
    

	# PGPASSWORD is the standard non-interactive way for psql.
	psql_cmd() {
		PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 "$@"
	}

	# Preflight: verify the target database exists (connect via maintenance DB).
	sql_escape_literal() {
		# Escape single quotes for SQL string literals.
		printf "%s" "$1" | sed "s/'/''/g"
	}

	ADMIN_DB=postgres
	psql_admin_cmd() {
		PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$ADMIN_DB" -v ON_ERROR_STOP=1 "$@"
	}

	# Try postgres, then template1.
	if ! psql_admin_cmd -tA -c "SELECT 1" >/dev/null 2>&1; then
		ADMIN_DB=template1
	fi

	esc_db_name=$(sql_escape_literal "$DB_NAME")
	exists=$(psql_admin_cmd -tA -c "SELECT 1 FROM pg_database WHERE datname='${esc_db_name}';" 2>/dev/null || true)
	if [ "$exists" != "1" ]; then
		echo "ERROR: Target database does not exist: $DB_NAME" >&2
		echo "Create it first (example):" >&2
		echo "  PGPASSWORD=*** psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $ADMIN_DB -v ON_ERROR_STOP=1 -c \"CREATE DATABASE \\\"$DB_NAME\\\";\"" >&2
		exit 1
	fi
fi

# Preflight: ensure we can connect to the target database (DATABASE_URL mode cannot check existence separately).
if ! psql_cmd -tA -c "SELECT 1" >/dev/null 2>&1; then
	echo "ERROR: Cannot connect to the target database." >&2
	echo "If you see 'database ... does not exist', create the database first." >&2
	# Re-run once to surface the underlying psql error.
	psql_cmd -tA -c "SELECT 1" >/dev/null
	exit 1
fi

echo "Checking database is empty..." >&2

# "Empty" means no user objects in public schema (tables/views/sequences/etc) and no functions.
empty_check_sql="
WITH public_classes AS (
	SELECT count(*)::int AS n
	FROM pg_class c
	JOIN pg_namespace n ON n.oid = c.relnamespace
	WHERE n.nspname = 'public'
		AND c.relkind IN ('r','p','v','m','S','f')
), public_funcs AS (
	SELECT count(*)::int AS n
	FROM pg_proc p
	JOIN pg_namespace n ON n.oid = p.pronamespace
	WHERE n.nspname = 'public'
)
SELECT (SELECT n FROM public_classes) AS class_count,
			 (SELECT n FROM public_funcs)  AS func_count;"

counts=$(psql_cmd -tA -c "$empty_check_sql")
class_count=${counts%%|*}
func_count=${counts#*|}

if [ "${class_count:-}" != "0" ] || [ "${func_count:-}" != "0" ]; then
	echo "ERROR: Refusing to seed: database is not empty (public schema already has objects)." >&2
	echo "Found: class_count=${class_count:-?} func_count=${func_count:-?}" >&2
	exit 1
fi

echo "Seeding schema from $SCHEMA_FILE ..." >&2
psql_cmd -f "$SCHEMA_FILE" >/dev/null

echo "Running post-seed checks..." >&2

post_check_sql=$(cat <<'SQL'
DO $$
BEGIN
	IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pgcrypto') THEN
		RAISE EXCEPTION 'pgcrypto extension missing after seeding';
	END IF;

	IF to_regclass('public.kinds') IS NULL THEN RAISE EXCEPTION 'missing table kinds'; END IF;
	IF to_regclass('public.nodes') IS NULL THEN RAISE EXCEPTION 'missing table nodes'; END IF;
	IF to_regclass('public.edges_kinds') IS NULL THEN RAISE EXCEPTION 'missing table edges_kinds'; END IF;
	IF to_regclass('public.edges') IS NULL THEN RAISE EXCEPTION 'missing table edges'; END IF;
	IF to_regclass('public.attachments') IS NULL THEN RAISE EXCEPTION 'missing table attachments'; END IF;

	PERFORM count(*) FROM kinds;
END $$;
SQL
)

psql_cmd -q -c "$post_check_sql" >/dev/null

echo "Seed completed and post-check passed." >&2
