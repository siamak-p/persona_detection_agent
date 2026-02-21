# JoowMe Agent — Installation & Setup Guide

## Prerequisites

| Requirement          | Version    | Notes                              |
|----------------------|------------|------------------------------------|
| **Python**           | 3.11+      | Required for async support         |
| **Docker & Docker Compose** | Latest | For infrastructure services       |
| **Git**              | Latest     | For cloning the repository         |
| **NVIDIA GPU** (optional) | CUDA 12+ | For local embedding model (BAAI/bge-m3) |
| **OpenAI API Key**   | —          | Required for LLM, STT, TTS        |

---

## Step 1: Clone the Repository

```bash
git clone <repository-url> joowme-agent
cd joowme-agent
```

---

## Step 2: Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate   # Linux/macOS
# or
venv\Scripts\activate      # Windows
```

---

## Step 3: Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> **Note:** The `requirements.txt` includes PyTorch with CUDA support. If you don't have a GPU, install the CPU-only version first:
> ```bash
> pip install torch --index-url https://download.pytorch.org/whl/cpu
> pip install -r requirements.txt
> ```

---

## Step 4: Start Infrastructure Services

Start all required services (Qdrant, PostgreSQL, Phoenix, Prometheus, Grafana) using Docker Compose:

```bash
docker compose up -d
```

This starts:

| Service                | Port  | Description                       |
|------------------------|-------|-----------------------------------|
| **Qdrant**             | 6333  | Vector database for semantic memory |
| **PostgreSQL 16**      | 5432  | Relational database               |
| **PostgreSQL Exporter**| 9187  | PostgreSQL metrics for Prometheus  |
| **Phoenix**            | 6006  | AI/LLM trace visualization        |
| **Prometheus**         | 9091  | Metrics collection                 |
| **Grafana**            | 3000  | Dashboards (admin/admin) ⚠️ **WIP** |

Verify all services are running:

```bash
docker compose ps
```

---

## Step 5: Configure Environment Variables

Create a `.env` file in the project root:

```bash
cp .env.example .env   # if .env.example exists
# or create manually:
touch .env
```

Add the following required variables:

```env
# ──────────────────────────────────────────
# Required Settings
# ──────────────────────────────────────────

# OpenAI API
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_BASE_URL=https://api.openai.com/v1    # or your OpenRouter/proxy URL

# PostgreSQL (must match docker-compose.yaml)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=joowme
POSTGRES_USER=joowme
POSTGRES_PASSWORD=joowme

# ──────────────────────────────────────────
# Optional Settings (with defaults)
# ──────────────────────────────────────────

# Vector Database
QDRANT_URL=http://localhost:6333

# Application
APP_ENV=development
LOG_LEVEL=INFO
TENANT_ID=default

# LLM Models (defaults shown)
COMPOSER_MODEL=gpt-4.1
CREATOR_MODEL=gpt-4.1
GUARDRAIL_MODEL=gpt-4o-mini
SUMMARIZER_MODEL=gpt-4.1
TONE_MODEL=gpt-4o-mini
FACT_EXTRACTOR_MODEL=gpt-4.1
MEM0_LLM_MODEL=openai/gpt-4o

# LLM Temperatures
COMPOSER_TEMPERATURE=0.6
CREATOR_TEMPERATURE=0.7
GUARDRAIL_TEMPERATURE=0.1
SUMMARIZER_TEMPERATURE=0.2
TONE_TEMPERATURE=0.3

# Memory & Embeddings
MEM0_EMBEDDING_MODEL=BAAI/bge-m3
MEM0_EMBEDDING_DIMS=1024
MESSAGE_COUNT_THRESHOLD=20

# Voice (optional)
VOICE_ENABLED=true
VOICE_TTS_ENABLED=false
VOICE_STT_MODEL=gpt-4o-audio-preview
VOICE_TTS_MODEL=tts-1
VOICE_TTS_VOICE=alloy

# Schedulers
SCHEDULER_ENABLED=true
TONE_SCHEDULER_INTERVAL_SECONDS=3600
FEEDBACK_SCHEDULER_INTERVAL_SECONDS=28800
```

---

## Step 6: Initialize Database

Run the database initialization script to create all required tables:

```bash
python scripts/init_databases.py
```

If you need to apply migrations:

```bash
python scripts/migrations.py
```

---

## Step 7: Download Embedding Model (Optional)

To pre-download the BAAI/bge-m3 embedding model for offline use:

```bash
python scripts/load_embedding_model.py
```

> If skipped, the model will be downloaded automatically on first startup (requires internet).

---

## Step 8: Run the Application

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Or without auto-reload (production):

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

The API will be available at: **http://localhost:8000**

### Verify It's Running

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "message": "PetaProcTwin API is running"
}
```

---

## Step 9: Run Streamlit Dashboard (Optional)

In a separate terminal:

```bash
cd streamlit_ui
streamlit run app.py --server.port 8501
```

Dashboard: **http://localhost:8501**

---

## Service Ports Summary

| Service              | URL                           | Purpose                    |
|----------------------|-------------------------------|----------------------------|
| **JoowMe API**      | http://localhost:8000          | Main API                   |
| **API Docs (Swagger)** | http://localhost:8000/docs   | Interactive API docs       |
| **Streamlit UI**     | http://localhost:8501          | Admin dashboard            |
| **Qdrant**           | http://localhost:6333          | Vector DB dashboard        |
| **Phoenix**          | http://localhost:6006          | AI tracing UI              |
| **Grafana**          | http://localhost:3000          | Metrics dashboards ⚠️ **WIP** |
| **Prometheus**       | http://localhost:9091          | Metrics query              |

---

## Troubleshooting

### PostgreSQL connection error
```
Make sure Docker containers are running:
  docker compose ps

Check PostgreSQL logs:
  docker compose logs postgres
```

### Qdrant connection error
```
Verify Qdrant is accessible:
  curl http://localhost:6333/healthz
```

### Embedding model download fails
```
Pre-download the model:
  python scripts/load_embedding_model.py

Or set a different embedding model in .env:
  MEM0_EMBEDDING_MODEL=text-embedding-3-small
```

### OpenAI API errors
```
Verify your API key:
  curl https://api.openai.com/v1/models \
    -H "Authorization: Bearer $OPENAI_API_KEY"
```

### Port conflicts
```
Check what's using a port:
  lsof -i :8000
  
Kill the process or change the port:
  uvicorn main:app --port 8001
```
