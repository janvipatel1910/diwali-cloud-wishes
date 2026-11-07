"""
Diwali Cloud Wishes - AWS Lambda backend
----------------------------------------
Runtime : Python 3.12+
Trigger : Amazon API Gateway (HTTP API, payload format 2.0)
Storage : Amazon DynamoDB
            TABLE_NAME          (default diwali_wishes)  one item per wish
            METRICS_TABLE_NAME  (default diwali_metrics) page-open counters

Routes
  POST /wish   -> saves one greeting request (name + optional city)
  POST /visit  -> counts one page open (no personal data)
  GET  /stats  -> aggregated, anonymous numbers only (no names)
"""

import json
import os
import re
import uuid
from collections import Counter
from datetime import datetime, timezone

import boto3

TABLE_NAME = os.environ.get("TABLE_NAME", "diwali_wishes")
METRICS_TABLE_NAME = os.environ.get("METRICS_TABLE_NAME", "diwali_metrics")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
metrics = dynamodb.Table(METRICS_TABLE_NAME)

# Letters (any language), spaces, dots, hyphens and apostrophes only.
SAFE_TEXT = re.compile(r"^[\w\s.'\-]+$", re.UNICODE)


def response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body),
    }


def clean(value, max_len):
    """Trim, collapse spaces and limit length."""
    value = " ".join(str(value or "").split())
    return value[:max_len]


def save_wish(event):
    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return response(400, {"error": "Body must be valid JSON."})

    name = clean(payload.get("name"), 40)
    city = clean(payload.get("city"), 30)

    if not name:
        return response(400, {"error": "Name is required."})
    if not SAFE_TEXT.match(name) or (city and not SAFE_TEXT.match(city)):
        return response(400, {"error": "Please use letters and spaces only."})

    now = datetime.now(timezone.utc)
    item = {
        "wish_id": str(uuid.uuid4()),
        "name": name,
        "city": city.title() if city else "Unknown",
        "created_at": now.isoformat(timespec="seconds"),
        "hour_utc": now.hour,
    }
    table.put_item(Item=item)

    return response(201, {"message": "Wish deployed", "wish_id": item["wish_id"]})


def count_visit():
    """Atomic counters: one total and one per day. No personal data stored."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for key in ("visits#total", "visits#" + day):
        metrics.update_item(
            Key={"metric": key},
            UpdateExpression="ADD #c :one",
            ExpressionAttributeNames={"#c": "count"},
            ExpressionAttributeValues={":one": 1},
        )
    return response(204, {})


def scan_all(tbl, **kwargs):
    while True:
        page = tbl.scan(**kwargs)
        yield from page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def get_stats():
    cities, by_day, by_hour = Counter(), Counter(), Counter()
    total = 0
    for row in scan_all(table, ProjectionExpression="city, created_at, hour_utc"):
        total += 1
        cities[row.get("city", "Unknown")] += 1
        created = str(row.get("created_at", ""))
        if created:
            by_day[created[:10]] += 1
        if "hour_utc" in row:
            by_hour[int(row["hour_utc"])] += 1

    visits_total, visits_by_day = 0, {}
    try:
        for row in scan_all(metrics):
            key, count = row.get("metric", ""), int(row.get("count", 0))
            if key == "visits#total":
                visits_total = count
            elif key.startswith("visits#"):
                visits_by_day[key.split("#", 1)[1]] = count
    except Exception:  # metrics table missing: still return wish stats
        pass

    return response(200, {
        "total_wishes": total,
        "top_cities": [{"city": c, "count": n} for c, n in cities.most_common(5)],
        "unique_cities": len([c for c in cities if c != "Unknown"]),
        "wishes_by_day": dict(sorted(by_day.items())),
        "wishes_by_hour_utc": [by_hour.get(h, 0) for h in range(24)],
        "visits_total": visits_total,
        "visits_by_day": dict(sorted(visits_by_day.items())),
    })


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "")

    if method == "OPTIONS":
        return response(204, {})
    if method == "POST" and path.endswith("/wish"):
        return save_wish(event)
    if method == "POST" and path.endswith("/visit"):
        return count_visit()
    if method == "GET" and path.endswith("/stats"):
        return get_stats()

    return response(404, {"error": "Route not found."})
