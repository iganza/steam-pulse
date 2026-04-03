Fix: Enforce metadata-before-reviews ordering in the crawler

Problem: When a review crawl is dispatched for an appid whose metadata hasn't been crawled yet (app_catalog.meta_status != 'done'),
reviews get ingested into the DB for a game that only has a stub row (name = "App {appid}"). The game then can't be found via search
or navigation until metadata is separately crawled.

File to change: src/lambda-functions/lambda_functions/crawler/handler.py — the _dispatch_to_spoke() function.

Fix: In the task == "reviews" branch, before dispatching, check _catalog_repo.get_meta_status(appid) (or equivalent — check what
method exists on CatalogRepository). If metadata hasn't been crawled (meta_status != 'done'), do not dispatch the review task.
Instead:

 1. Enqueue a metadata crawl for this appid onto the app-crawl SQS queue (use the existing _enqueue_meta_crawl helper or equivalent —
 check the codebase for how metadata is enqueued).
 2. Re-enqueue the review crawl message back onto the review-crawl SQS queue (so it gets picked up after metadata completes).
 3. Log a warning: "appid=%s has no metadata yet — queuing metadata first, re-enqueuing reviews".

Important constraints:

 - Do NOT remove ensure_stub from ingest_spoke_reviews — it's still needed for the FK constraint in edge cases. It was already fixed 
to use DO NOTHING instead of DO UPDATE.
 - Check CatalogRepository for the right method name to read meta_status — don't assume.
 - Check the existing SQS enqueue helpers in handler.py and crawl_service.py — reuse them, don't invent new ones.
 - Follow the existing 3-layer pattern: any new DB reads stay in the repository, dispatch/queue logic stays in the handler.
 - All existing tests must still pass (poetry run pytest -v).
