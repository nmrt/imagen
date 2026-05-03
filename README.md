# Imagen Creative Automation POC

Minimal local-first implementation based on `instructions.md`:
- FastAPI backend with LangGraph/LangChain agent flow
- GraphQL endpoint for querying generation runs
- Upload support for `campaign.json` + source images
- Generated image preview + ZIP download in a Next.js UI
- Real Imagen generation via Vertex AI
- Queue-compatible async job boundary (`/generate/submit`, `/jobs/{job_id}`)

## Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export VERTEX_PROJECT_ID="your-gcp-project-id"
export VERTEX_LOCATION="us-central1" # optional
export VERTEX_IMAGEN_MODEL="imagen-3.0-generate-002" # optional

gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID

uvicorn app.main:app --reload
```

Backend runs at <http://localhost:8000>:
- `POST /generate` multipart (`campaign_json`, `images[]`)
- `POST /generate/submit` multipart (`campaign_json`, `images[]`) returns `job_id`
- `GET /jobs/{job_id}` poll for queued/running/succeeded/failed
- `GET /health`
- `POST /graphql`
- `GET /runs/...` static generated assets and archives

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Set optional env var in frontend:
- `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`

Open <http://localhost:3000>, upload `campaign.sample.json`, add optional images, then generate creatives.
