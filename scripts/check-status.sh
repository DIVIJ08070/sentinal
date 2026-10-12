#!/usr/bin/env bash
# Quick status check to verify Sentinel is actively recording plates
echo "=========================================================="
echo "           SENTINEL OVERNIGHT LIVENESS CHECK              "
echo "=========================================================="

# 1. Check caffeinate (Mac sleep prevention)
if pgrep caffeinate >/dev/null; then
    echo "☕ Mac Sleep Guard (caffeinate):  [ACTIVE - Mac will NOT sleep]"
else
    echo "⚠️ Mac Sleep Guard (caffeinate):  [NOT RUNNING - Mac may sleep!]"
fi

# 2. Check Overnight Cycler
if pgrep -f "focused_cycler|round_robin_worker" >/dev/null 2>&1; then
    echo "🔄 Overnight ANPR Cycler:       [ACTIVE - 13m Full-Loop Soaks Across Top Cameras]"
else
    echo "⚠️ Overnight ANPR Cycler:       [DOWN]"
fi

# 3. Check Video ANPR engine (:8895)
if lsof -i :8895 >/dev/null 2>&1; then
    echo "⚡ Live Video ANPR Studio (:8895): [ACTIVE & READY]"
else
    echo "⚠️ Live Video ANPR Studio (:8895): [DOWN]"
fi

echo "----------------------------------------------------------"
echo "DATABASE TOTALS ACROSS ALL 30 CAMERAS:"
docker exec -i sentinel-db-1 psql -U sentinel -d sentinel -c "
SELECT 
    count(*) as total_sightings, 
    count(plate) as total_plates_read,
    count(DISTINCT plate) as unique_plates,
    count(DISTINCT camera_id) as cameras_with_data
FROM detections;

SELECT 
    c.id, 
    c.external_id,
    c.name, 
    count(d.id) as sightings, 
    count(d.plate) as plates
FROM cameras c 
LEFT JOIN detections d ON c.id = d.camera_id 
GROUP BY c.id, c.external_id, c.name 
HAVING count(d.id) > 0 
ORDER BY plates DESC, sightings DESC
LIMIT 10;
"

echo "=========================================================="
