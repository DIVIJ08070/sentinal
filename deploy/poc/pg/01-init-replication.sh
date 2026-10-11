#!/bin/bash
# Runs once during the primary's initdb. Creates a replication role + a
# physical replication slot and allows the replica to connect for streaming.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replicator';
  SELECT pg_create_physical_replication_slot('replica_slot');
EOSQL

# Allow the replicator role to open replication connections from the compose network.
cat >> "$PGDATA/pg_hba.conf" <<-EOF
host    replication    replicator    0.0.0.0/0    scram-sha-256
EOF
