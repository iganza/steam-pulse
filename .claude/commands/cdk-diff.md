# Show CDK infrastructure diff

Show what infrastructure changes would be deployed.

Steps:
1. Run: `poetry run cdk diff`
2. Summarise the changes in plain English — what resources are being added, modified, or destroyed
3. Flag any DESTRUCTIVE changes (deletions, replacements) prominently
4. Remind me to check that data_stack resources have termination_protection=True before deploying
