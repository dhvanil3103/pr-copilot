# e2e only. Build context: tests/e2e/mocks
FROM python:3.12.8-slim-bookworm
RUN useradd --system --uid 10001 --no-create-home mock
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY anthropic/app.py .
USER mock
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
