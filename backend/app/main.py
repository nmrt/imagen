from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Dict, List
from uuid import UUID, uuid4

import strawberry
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from strawberry.fastapi import GraphQLRouter

from .agent import build_graph
from .queue import InMemoryJobQueue
from .schemas import CampaignBrief, GenerationResult, JobResult, JobStatus, ProductResult
from .storage import write_manifest, zip_run

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Imagen Campaign Generator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/runs", StaticFiles(directory=RUNS_DIR), name="runs")

graph = build_graph()
RUN_RESULTS: Dict[str, GenerationResult] = {}
JOB_QUEUE = InMemoryJobQueue()


def _to_web_path(absolute_path: str) -> str:
    path = Path(absolute_path)
    rel = path.relative_to(RUNS_DIR)
    return f"/runs/{rel.as_posix()}"


async def _parse_and_validate_campaign(campaign_json: UploadFile) -> CampaignBrief:
    if campaign_json.filename is None or not campaign_json.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="campaign_json must be a .json file")
    try:
        payload = json.loads((await campaign_json.read()).decode("utf-8"))
        return CampaignBrief.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _persist_inputs(run_dir: Path, images: List[UploadFile]) -> List[Path]:
    input_dir = run_dir / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    image_paths: List[Path] = []
    for image in images:
        if image.filename is None:
            continue
        target = input_dir / image.filename
        target.write_bytes(await image.read())
        image_paths.append(target)
    return image_paths


def _run_generation(run_id: str, brief: CampaignBrief, image_paths: List[Path]) -> GenerationResult:
    run_dir = RUNS_DIR / run_id
    output_dir = run_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "brief": brief,
        "image_paths": image_paths,
        "output_dir": output_dir,
        "prompt_map": {},
        "source_context": "",
        "rendered": {},
    }
    final_state = graph.invoke(state)

    products: List[ProductResult] = []
    for product, aspect_map in final_state["rendered"].items():
        products.append(
            ProductResult(
                product=product,
                images={name: _to_web_path(path) for name, path in aspect_map.items()},
            )
        )

    result = GenerationResult(
        run_id=UUID(run_id),
        campaign_id=brief.campaign_id,
        products=products,
        zip_path="",
        manifest_path="",
    )
    manifest_path = write_manifest(run_dir, result)
    zip_path = zip_run(run_dir, run_id)
    result = result.model_copy(
        update={
            "zip_path": _to_web_path(str(zip_path)),
            "manifest_path": _to_web_path(str(manifest_path)),
        }
    )
    RUN_RESULTS[run_id] = result
    return result


# ProductOutput and RunOutput could be imported from schemas.py
# Corresponding types are ProductResult and GenerationResult.
@strawberry.type
class ProductOutput:
    product: str
    images: strawberry.scalars.JSON


@strawberry.type
class RunOutput:
    run_id: str
    campaign_id: str
    zip_path: str
    manifest_path: str
    products: List[ProductOutput]


@strawberry.type
class Query:
    @strawberry.field
    def run(self, run_id: str) -> RunOutput | None:
        result = RUN_RESULTS.get(run_id)
        if result is None:
            return None
        return RunOutput(
            run_id=str(result.run_id),
            campaign_id=result.campaign_id,
            zip_path=result.zip_path,
            manifest_path=result.manifest_path,
            products=[
                ProductOutput(product=p.product, images=p.images)
                for p in result.products
            ],
        )

    @strawberry.field
    def job(self, job_id: str) -> strawberry.scalars.JSON | None:
        job = JOB_QUEUE.get(job_id)
        if job is None:
            return None
        return {
            "job_id": job.id,
            "status": job.status.value,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "result": job.result,
            "error": job.error,
        }


app.include_router(GraphQLRouter(strawberry.Schema(query=Query)), prefix="/graphql")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/generate", response_model=GenerationResult)
async def generate(
    campaign_json: UploadFile = File(...),
    images: List[UploadFile] = File(default_factory=list),
):
    brief = await _parse_and_validate_campaign(campaign_json)
    run_id = str(uuid4())
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    image_paths = await _persist_inputs(run_dir, images)
    return await asyncio.to_thread(_run_generation, run_id, brief, image_paths)


@app.post("/generate/submit", response_model=JobResult)
async def generate_submit(
    campaign_json: UploadFile = File(...),
    images: List[UploadFile] = File(default_factory=list),
):
    brief = await _parse_and_validate_campaign(campaign_json)
    run_id = str(uuid4())
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    image_paths = await _persist_inputs(run_dir, images)

    async def task() -> dict:
        result = await asyncio.to_thread(_run_generation, run_id, brief, image_paths)
        return result.model_dump(mode="json")

    job_id = JOB_QUEUE.submit(task)
    job = JOB_QUEUE.get(job_id)
    if job is None:
        raise HTTPException(status_code=500, detail="failed to create job")

    return JobResult(
        job_id=job.id,
        status=JobStatus(job.status.value),
        created_at=job.created_at,
        updated_at=job.updated_at,
        result=None,
        error=job.error,
    )


@app.get("/jobs/{job_id}", response_model=JobResult)
def get_job(job_id: str):
    job = JOB_QUEUE.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    result = GenerationResult.model_validate(job.result) if job.result else None
    return JobResult(
        job_id=job.id,
        status=JobStatus(job.status.value),
        created_at=job.created_at,
        updated_at=job.updated_at,
        result=result,
        error=job.error,
    )
