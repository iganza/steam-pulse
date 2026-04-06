Hypothesis to verify

The review crawl uses a paginated re-queue pattern:

 1. spoke-crawl-queue (SQS, eu-west-1) → triggers spoke Lambda (eu-west-1, infra/stacks/spoke_stack.py)
 2. Spoke fetches 1,000 reviews from Steam, sends result + next_cursor → spoke-results-queue (SQS, us-west-2)
 3. spoke-results-queue → triggers ingest Lambda (us-west-2, infra/stacks/compute_stack.py)
 4. Ingest processes reviews. If next_cursor != None (more pages remain), it re-queues directly back to the spoke's SQS queue: 
src/lambda-functions/lambda_functions/crawler/ingest_handler.py lines ~292-303

So the chain is: spoke-crawl-queue → spoke Lambda → spoke-results-queue → ingest Lambda → spoke-crawl-queue → spoke Lambda → ...

AWS X-Ray propagates X-Amzn-Trace-Id through SQS message attributes. Lambda sees the spoke function appearing twice in the ancestor
chain and classifies it as recursive — even though it's two different invocations of the same function doing legitimate paginated
work.

Verification steps:

 1. Check aws lambda get-function-recursion-config for the spoke Lambda in eu-west-1 — confirm it returns Terminate (the default)
 2. Read infra/stacks/spoke_stack.py — find the PythonFunction definition for the spoke Lambda (~line 131). Confirm there is no 
recursive_loop prop set.
 3. Read infra/stacks/compute_stack.py — find the PythonFunction for the ingest handler (look for IngestFn or ingest_handler). 
Confirm no recursive_loop prop.
 4. Read src/lambda-functions/lambda_functions/crawler/ingest_handler.py lines ~285-310 to confirm the re-queue pattern sends to a 
spoke SQS queue (not the review-crawl-queue)

The fix (implement after verifying):

Add recursive_loop=lambda_.RecursiveLoop.ALLOW to:

 1. The spoke PythonFunction in infra/stacks/spoke_stack.py
 2. The ingest PythonFunction in infra/stacks/compute_stack.py

Both use PythonFunction from aws_cdk.aws_lambda_python_alpha, which inherits all props from aws_cdk.aws_lambda.Function including 
recursive_loop. The import for aws_cdk.aws_lambda as lambda_ is already present in both files.

Do not modify any handler code — this is a CDK-only change. Do not deploy — just make the CDK change and confirm cdk synth passes
cleanly.
