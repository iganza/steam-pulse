FROM public.ecr.aws/awsguru/aws-lambda-adapter:0.8.4 AS lambda-adapter
FROM public.ecr.aws/lambda/python:3.12

COPY --from=lambda-adapter /lambda-adapter /opt/extensions/lambda-adapter
ENV PORT=8080

WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN pip install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --without crawler,infra,dev --no-root

COPY steampulse/ ./steampulse/
CMD ["uvicorn", "steampulse.api:app", "--host", "0.0.0.0", "--port", "8080"]
