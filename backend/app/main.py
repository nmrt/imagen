from __future__ import annotations

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
from .schemas import CampaignBrief, GenerationResult, ProductResult
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


def _to_web_path(absolute_path: str) -> str:
    path = Path(absolute_path)
    rel = path.relative_to(RUNS_DIR)
    return f"/runs/{rel.as_posix()}"


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


app.include_router(GraphQLRouter(strawberry.Schema(query=Query)), prefix="/graphql")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/generate", response_model=GenerationResult)
async def generate(
    campaign_json: UploadFile = File(...),
    images: List[UploadFile] = File(default_factory=list),
):
    if campaign_json.filename is None or not campaign_json.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="campaign_json must be a .json file")

    try:
        payload = json.loads((await campaign_json.read()).decode("utf-8"))
        brief = CampaignBrief.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    run_id = uuid4()
    run_dir = RUNS_DIR / str(run_id)
    input_dir = run_dir / "inputs"
    output_dir = run_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    image_paths: List[Path] = []
    for image in images:
        if image.filename is None:
            continue
        target = input_dir / image.filename
        target.write_bytes(await image.read())
        image_paths.append(target)

    state = {
        "brief": brief,
        "image_paths": image_paths,
        "output_dir": output_dir,
        "prompt_map": {},
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
        run_id=run_id,
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
    RUN_RESULTS[str(run_id)] = result
    return result
