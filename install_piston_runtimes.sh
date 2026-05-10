#!/usr/bin/env bash
# install_piston_runtimes.sh
# ──────────────────────────
# Installs the Python and JavaScript (Node.js) runtimes into the
# running Piston container.
#
# Run this ONCE after starting Piston with:
#   docker-compose -f docker-compose.piston.yml up -d
#
# Then run this script:
#   bash install_piston_runtimes.sh

set -e

PISTON_URL="http://localhost:2000"

echo "Waiting for Piston to be ready..."
until curl -sf "$PISTON_URL/api/v2/runtimes" > /dev/null; do
  sleep 2
done
echo "Piston is up."

echo ""
echo "Installing Python 3.10.0..."
curl -s "$PISTON_URL/api/v2/packages" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"language": "python", "version": "3.10.0"}' | python3 -m json.tool

echo ""
echo "Installing Node.js (JavaScript) 18.15.0..."
curl -s "$PISTON_URL/api/v2/packages" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"language": "javascript", "version": "18.15.0"}' | python3 -m json.tool

echo ""
echo "Installed runtimes:"
curl -s "$PISTON_URL/api/v2/runtimes" | python3 -m json.tool

echo ""
echo "Done. Piston is ready to execute Python and JavaScript code."