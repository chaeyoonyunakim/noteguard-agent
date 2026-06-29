FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Runtime dep set — mirrors the [project] dependencies in pyproject.toml,
# plus the [nlp] extra (Presidio + spaCy) so free-text names are de-identified.
RUN pip install --no-cache-dir \
    "fastapi>=0.109.0" \
    "uvicorn[standard]>=0.27.0" \
    "langgraph>=0.2.0" \
    "langchain>=0.3.0" \
    "langchain-google-genai>=2.0.0" \
    "langchain-tavily>=0.1.0" \
    "langsmith>=0.1.0" \
    "python-dotenv>=1.0.0" \
    "huggingface_hub>=0.20.0" \
    "presidio-analyzer>=2.2.0" \
    "spacy>=3.7.0,<4"

# spaCy model for Presidio NER. _md balances recall vs image size; override with
# NOTEGUARD_SPACY_MODEL (e.g. en_core_web_lg) if you also bake that model in.
RUN python -m spacy download en_core_web_md
ENV NOTEGUARD_SPACY_MODEL=en_core_web_md

COPY . .

# Bake the synthetic dataset into the image so /samples works without runtime downloads
RUN python src/fetch_dataset.py

ENV PYTHONUNBUFFERED=1
EXPOSE 7860

CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "7860"]
