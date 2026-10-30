#!/usr/bin/env bash
# Run the Task 2 queries against the Docker containers and save the output.

#Used AI for help on this script

#   ./database/run_queries.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p database/results

echo "Running MySQL queries ..."
# --verbose echoes each statement before its result. The mysql client would also echo every
# comment line as its own block, so only the "-- Qn." title lines are sent, and awk prints
# those as plain headings.
awk '!/^--/ || /^-- Q[0-9]+\./' database/mysql/queries.sql \
  | docker compose exec -T mysql mysql -upower -ppowerpass --table --verbose --verbose household_power 2>/dev/null \
  | awk '
      /^--------------$/ {
        if ((getline l1) > 0 && l1 ~ /^-- Q[0-9]+\./) { getline; getline; print "\n" l1; next }
        print; print l1; next
      }
      /^Query OK, 0 rows affected/ { next }
      { print }' \
  | cat -s \
  > database/results/mysql_query_results.txt

echo "Running MongoDB queries ..."
docker compose exec -T mongo sh -c 'cat > /tmp/queries.js && mongosh --quiet -u root -p rootpass --authenticationDatabase admin --file /tmp/queries.js' \
  < database/mongodb/queries.js > database/results/mongodb_query_results.txt

echo "Results written to database/results/"
