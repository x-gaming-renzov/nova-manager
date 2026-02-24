#!/bin/bash
set -e

BASE_URL="http://localhost:8000/api/v1"
CLICKHOUSE_CONTAINER="nova-manager-clickhouse-1"

echo "============================================"
echo "  Nova Manager - Full Flow Test"
echo "============================================"
echo ""

# ─── Step 1: Register a user ───
echo ">>> Step 1: Registering user..."
REGISTER_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"test1234","name":"Test User","company":"TestCo"}')

echo "$REGISTER_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$REGISTER_RESPONSE"

ACCESS_TOKEN=$(echo "$REGISTER_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null)

if [ -z "$ACCESS_TOKEN" ]; then
  echo "ERROR: Failed to get access_token from register. Response above."
  exit 1
fi
echo "Access token: ${ACCESS_TOKEN:0:30}..."
echo ""

# ─── Step 2: Create an app (provisions ClickHouse database + tables) ───
echo ">>> Step 2: Creating app (provisions ClickHouse tables)..."
APP_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/apps" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -d '{"name":"My App","description":"Test app"}')

echo "$APP_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$APP_RESPONSE"

# Extract new access token (app-scoped)
NEW_ACCESS_TOKEN=$(echo "$APP_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null)

if [ -z "$NEW_ACCESS_TOKEN" ]; then
  echo "ERROR: Failed to get access_token from create app. Response above."
  exit 1
fi
ACCESS_TOKEN="$NEW_ACCESS_TOKEN"
echo "New access token (app-scoped): ${ACCESS_TOKEN:0:30}..."
echo ""

# ─── Step 3: Get SDK credentials ───
echo ">>> Step 3: Getting SDK credentials..."
SDK_RESPONSE=$(curl -s "$BASE_URL/auth/sdk-credentials" \
  -H "Authorization: Bearer $ACCESS_TOKEN")

echo "$SDK_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$SDK_RESPONSE"

SDK_API_KEY=$(echo "$SDK_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['sdk_api_key'])" 2>/dev/null)

if [ -z "$SDK_API_KEY" ]; then
  echo "ERROR: Failed to get sdk_api_key. Response above."
  exit 1
fi
echo "SDK API Key: ${SDK_API_KEY:0:30}..."
echo ""

# ─── Step 4: Create a user (tests user profile tracking) ───
echo ">>> Step 4: Creating a user with profile..."
USER_RESPONSE=$(curl -s -X POST "$BASE_URL/users/create-user/" \
  -H "Content-Type: application/json" \
  -H "X-SDK-API-Key: $SDK_API_KEY" \
  -d '{"user_id":"user_test_001","user_profile":{"name":"John Doe","level":"5","country":"US"}}')

echo "$USER_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$USER_RESPONSE"
echo ""

# ─── Step 5: Track events ───
echo ">>> Step 5: Tracking events..."

# Event 1: button_click
EVENT1_RESPONSE=$(curl -s -X POST "$BASE_URL/metrics/track-event/" \
  -H "Content-Type: application/json" \
  -H "X-SDK-API-Key: $SDK_API_KEY" \
  -d '{"user_id":"user_test_001","event_name":"button_click","event_data":{"button_id":"signup","page":"home"},"timestamp":"2026-02-23T12:00:00Z"}')
echo "  button_click: $EVENT1_RESPONSE"

# Event 2: page_view
EVENT2_RESPONSE=$(curl -s -X POST "$BASE_URL/metrics/track-event/" \
  -H "Content-Type: application/json" \
  -H "X-SDK-API-Key: $SDK_API_KEY" \
  -d '{"user_id":"user_test_001","event_name":"page_view","event_data":{"page":"/dashboard","referrer":"/home"},"timestamp":"2026-02-23T12:01:00Z"}')
echo "  page_view:    $EVENT2_RESPONSE"

# Event 3: purchase
EVENT3_RESPONSE=$(curl -s -X POST "$BASE_URL/metrics/track-event/" \
  -H "Content-Type: application/json" \
  -H "X-SDK-API-Key: $SDK_API_KEY" \
  -d '{"user_id":"user_test_001","event_name":"purchase","event_data":{"item":"sword","amount":"9.99","currency":"USD"},"timestamp":"2026-02-23T12:02:00Z"}')
echo "  purchase:     $EVENT3_RESPONSE"

echo ""

# ─── Step 6: Wait for worker to process ───
echo ">>> Step 6: Waiting 5s for worker to process jobs..."
sleep 5
echo ""

# ─── Step 7: Verify ClickHouse data ───
echo ">>> Step 7: Verifying ClickHouse data..."
echo ""

echo "--- Databases ---"
docker exec "$CLICKHOUSE_CONTAINER" clickhouse-client --query "SHOW DATABASES" 2>/dev/null
echo ""

# Find the org/app database
DB_NAME=$(docker exec "$CLICKHOUSE_CONTAINER" clickhouse-client --query "SHOW DATABASES" 2>/dev/null | grep "^org_")

if [ -z "$DB_NAME" ]; then
  echo "WARNING: No org_* database found yet. Worker may still be processing."
  echo "Re-run this section after the worker finishes."
  echo ""
else
  echo "Found database: $DB_NAME"
  echo ""

  echo "--- Tables ---"
  docker exec "$CLICKHOUSE_CONTAINER" clickhouse-client --query "SHOW TABLES FROM \`$DB_NAME\`" 2>/dev/null
  echo ""

  echo "--- raw_events ---"
  docker exec "$CLICKHOUSE_CONTAINER" clickhouse-client --query "SELECT * FROM \`$DB_NAME\`.raw_events FORMAT PrettyCompact" 2>/dev/null
  echo ""

  echo "--- event_props ---"
  docker exec "$CLICKHOUSE_CONTAINER" clickhouse-client --query "SELECT * FROM \`$DB_NAME\`.event_props FORMAT PrettyCompact" 2>/dev/null
  echo ""

  echo "--- user_profile_props ---"
  docker exec "$CLICKHOUSE_CONTAINER" clickhouse-client --query "SELECT * FROM \`$DB_NAME\`.user_profile_props FORMAT PrettyCompact" 2>/dev/null
  echo ""

  echo "--- user_experience ---"
  docker exec "$CLICKHOUSE_CONTAINER" clickhouse-client --query "SELECT * FROM \`$DB_NAME\`.user_experience FORMAT PrettyCompact" 2>/dev/null
  echo ""

  echo "--- Row counts ---"
  docker exec "$CLICKHOUSE_CONTAINER" clickhouse-client --query "SELECT 'raw_events' AS tbl, count() AS cnt FROM \`$DB_NAME\`.raw_events UNION ALL SELECT 'event_props', count() FROM \`$DB_NAME\`.event_props UNION ALL SELECT 'user_profile_props', count() FROM \`$DB_NAME\`.user_profile_props UNION ALL SELECT 'user_experience', count() FROM \`$DB_NAME\`.user_experience FORMAT PrettyCompact" 2>/dev/null
  echo ""
fi

echo "============================================"
echo "  Test flow complete!"
echo "============================================"
