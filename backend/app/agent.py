from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List
from typing_extensions import TypedDict
from pydantic import TypeAdapter

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from vertexai import init as vertex_init
from vertexai.preview.vision_models import ImageGenerationModel

from .schemas import CampaignBrief


ASPECTS: Dict[str, str] = {
    "1x1": "1:1",
    "9x16": "9:16",
    "16x9": "16:9",
}


class AgentState(TypedDict):
    brief: CampaignBrief
    image_paths: List[Path]
    output_dir: Path
    prompt_map: Dict[str, str]
    source_context: str
    rendered: Dict[str, Dict[str, str]]


def _create_prompts(state: AgentState) -> AgentState:
    brief = state["brief"]
    template = ChatPromptTemplate.from_template(
        "Create a concise creative direction for product '{product}' in region '{region}' "
        "targeting '{audience}'. Campaign message: '{message}'."
    )
    prompt_map: Dict[str, str] = {}
    for product in brief.products:
        messages = template.format_messages(
            product=product,
            region=brief.target_region,
            audience=brief.target_audience,
            message=brief.campaign_message,
        )
        prompt_map[product] = messages[0].content
    state["prompt_map"] = prompt_map
    if state["image_paths"]:
        state["source_context"] = (
            "Reference source images were uploaded and should be used as stylistic guidance "
            "for color, composition, and product framing."
        )
    else:
        state["source_context"] = "No reference images were uploaded."
    return state


class ImagenClient:
    def __init__(self) -> None:
        project = os.getenv("VERTEX_PROJECT_ID")
        location = os.getenv("VERTEX_LOCATION", "us-central1")
        # gemini-3-pro-image-preview
        model_name = os.getenv("VERTEX_IMAGEN_MODEL", "imagen-4.0-generate-001") # imagen-3.0-generate-002
        print(f"Project: {project}, Location: {location}, Model: {model_name}")
        if not project:
            raise RuntimeError("Set VERTEX_PROJECT_ID before generating with Imagen.")
        vertex_init(project=project, location=location)
        self.model = ImageGenerationModel.from_pretrained(model_name)

    def generate(self, prompt: str, aspect_ratio: str, output_path: Path) -> None:
        print(f"ImagenClient.generate: {prompt}, aspect_ratio: {aspect_ratio}, output_path: {output_path}")
        result = self.model.generate_images(
            prompt=prompt,
            number_of_images=1,
            aspect_ratio=aspect_ratio,
            safety_filter_level="block_some",
            person_generation="allow_adult",
            negative_prompt="",
            guidance_scale=7, # 10+ for stricter prompt adherence
        )
        if not result.images:
            raise RuntimeError("Imagen returned no images.")
        result.images[0].save(location=str(output_path))


def _render_images(state: AgentState) -> AgentState:
    adapter = TypeAdapter(AgentState)
    print(f"_render_images state: {adapter.dump_json(state, indent=2).decode('utf-8')}")
    brief = state["brief"]
    output_dir = state["output_dir"]
    prompt_map = state["prompt_map"]
    source_context = state["source_context"]
    rendered: Dict[str, Dict[str, str]] = {}

    imagen = ImagenClient()
    for product in brief.products:
        product_slug = product.lower().replace(" ", "_")
        product_dir = output_dir / product_slug
        product_dir.mkdir(parents=True, exist_ok=True)
        rendered[product] = {}

        for aspect_name, aspect_ratio in ASPECTS.items():
            filename = f"{product_slug}_{aspect_name}.png"
            output_path = product_dir / filename
            prompt = (
                f"{prompt_map[product]} "
                f"Campaign message: {brief.campaign_message}. "
                f"Product SKU: {product}. "
                f"Target region: {brief.target_region}. "
                f"Use brand colors {brief.color_palette}. "
                f"{source_context}. "
                "Create a social ad background with clean composition and realistic lighting. "
                "Leave clear negative space for headline and CTA overlay. "
                "Localize the message to the target region."
            )
            imagen.generate(prompt=prompt, aspect_ratio=aspect_ratio, output_path=output_path)
            rendered[product][aspect_name] = str(output_path)

    state["rendered"] = rendered
    return state


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("prompt_builder", _create_prompts)
    graph.add_node("renderer", _render_images)
    graph.add_edge(START, "prompt_builder")
    graph.add_edge("prompt_builder", "renderer")
    graph.add_edge("renderer", END)
    return graph.compile()
