# Scaffold a new CDK stack

Create a new CDK stack following project conventions.

Usage: /new-stack <stack-name> <description>

Rules (mandatory — from CLAUDE.md):
- No physical resource names (let CDK generate)
- No env var lookups inside the construct — pass as props
- Secrets via AWS Secrets Manager, referenced by ARN
- If the stack contains stateful resources (RDS, S3, DynamoDB), add termination_protection=True
- Add the stack to infra/application_stage.py
- Register it in infra/app.py

Create the file at: `infra/stacks/<stack-name>_stack.py`
