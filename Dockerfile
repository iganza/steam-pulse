FROM python:3.10-slim
WORKDIR /app
RUN pip install poetry
COPY pyproject.toml poetry.lock* ./
RUN poetry install --without crawler --no-root
COPY . .
RUN poetry install --without crawler
CMD ["poetry", "run", "uvicorn", "steampulse.api:app", "--host", "0.0.0.0", "--port", "8000"]
