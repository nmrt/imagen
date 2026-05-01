# Imagen Creative Automation POC

Minimal local-first implementation based on `instructions.md`:
- FastAPI backend with LangGraph/LangChain agent flow
- GraphQL endpoint for querying generation runs
- Upload support for `campaign.json` + source images
- Generated image preview + ZIP download in a Next.js UI

## Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Backend runs at `http://localhost:8000`:
- `POST /generate` multipart (`campaign_json`, `images[]`)
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

Open `http://localhost:3000`, upload `campaign.sample.json`, add optional images, then generate creatives.
