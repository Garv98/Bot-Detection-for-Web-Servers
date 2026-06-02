#!/bin/bash
# Wait briefly for the HBase master, then launch the Thrift gateway.
# Stored as a file (not inline) because bde2020/hbase-standalone's entrypoint
# uses `exec $@` without quotes — multi-line inline commands get word-split
# and bash silently runs only the first whitespace-delimited token.
set -e
echo "[thrift-init] waiting 60s for HBase master to settle..."
sleep 60
echo "[thrift-init] launching hbase thrift gateway"
exec hbase thrift start
