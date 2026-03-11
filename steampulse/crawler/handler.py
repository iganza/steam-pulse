"""AWS Lambda handler — triggered by SQS. Each message contains an appid."""

import asyncio
import json
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from .app_crawler import crawl_app
from .review_crawler import crawl_reviews


def handler(event: dict[str, Any], context: Any) -> dict:
    """
    SQS-triggered Lambda handler.
    Each SQS record is expected to have a JSON body with an `appid` field.

    Example SQS message body:
        {"appid": 440}

    or with explicit crawl type:
        {"appid": 440, "crawl_type": "app"}   # full app+tag crawl (default)
        {"appid": 440, "crawl_type": "reviews"} # review-count update only
    """
    records = event.get("Records", [])
    results = []

    for record in records:
        try:
            body = json.loads(record.get("body", "{}"))
            appid = int(body["appid"])
            crawl_type = body.get("crawl_type", "app")
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            print(f"[handler] Invalid SQS message: {e} — body: {record.get('body')}")
            results.append({"status": "error", "detail": str(e)})
            continue

        try:
            if crawl_type == "reviews":
                success = asyncio.run(crawl_reviews(appid))
            else:
                success = asyncio.run(crawl_app(appid))
            results.append({"appid": appid, "status": "ok" if success else "skipped"})
        except Exception as e:
            print(f"[handler] Error crawling appid {appid}: {e}")
            results.append({"appid": appid, "status": "error", "detail": str(e)})

    return {"statusCode": 200, "results": results}
