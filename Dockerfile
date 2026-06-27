FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Light dep set — superlinked/torch omitted (large; agent falls back to Gemini-only)
RUN pip install --no-cache-dir \
    "fastapi>=0.109.0" \
    "uvicorn[standard]>=0.27.0" \
    "langgraph>=0.2.0" \
    "langchain>=0.3.0" \
    "langchain-google-genai>=2.0.0" \
    "langchain-tavily>=0.1.0" \
    "langsmith>=0.1.0" \
    "python-dotenv>=1.0.0" \
    "huggingface_hub>=0.20.0"

COPY . .

# Bake the synthetic dataset into the image so /samples works without runtime downloads
RUN python scripts/fetch_dataset.py

ENV PYTHONUNBUFFERED=1
EXPOSE 7860

CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "7860"]
