"""
Diwali Cloud Wishes - AWS Lambda backend
----------------------------------------
Runtime : Python 3.12
Trigger : Amazon API Gateway (HTTP API, payload format 2.0)
Storage : Amazon DynamoDB table (name from the TABLE_NAME environment variable)

Routes
  POST /wish   -> saves one greeting request (name + optional city)
  GET  /stats  -> returns aggregated, anonymous numbers only (no names)
"""

import json
import os
import re
import uuid
from collections import Counter
from datetime import datetime, timezone

import boto3

TABLE_NAME = os.environ.get("TABLE_NAME", "diwali_wishes")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

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


def get_stats():
    """Scan only the fields needed for anonymous counts."""
    cities = Counter()
    total = 0
    scan_kwargs = {"ProjectionExpression": "city"}

    while True:
        page = table.scan(**scan_kwargs)
        for row in page.get("Items", []):
            cities[row.get("city", "Unknown")] += 1
            total += 1
        if "LastEvaluatedKey" not in page:
            break
        scan_kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    top_cities = [{"city": c, "count": n} for c, n in cities.most_common(5)]
    return response(200, {"total_wishes": total, "top_cities": top_cities})


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "")

    if method == "OPTIONS":
        return response(204, {})
    if method == "POST" and path.endswith("/wish"):
        return save_wish(event)
    if method == "GET" and path.endswith("/stats"):
        return get_stats()

    return response(404, {"error": "Route not found."})
