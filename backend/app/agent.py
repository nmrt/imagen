from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Dict, List, TypedDict

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from PIL import Image, ImageDraw, ImageFont

from .schemas import CampaignBrief


ASPECTS: Dict[str, tuple[int, int]] = {
    "1x1": (1024, 1024),
    "9x16": (1080, 1920),
    "16x9": (1920, 1080),
}


class AgentState(TypedDict):
    brief: CampaignBrief
    image_paths: List[Path]
    output_dir: Path
    prompt_map: Dict[str, str]
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
    return state


def _render_images(state: AgentState) -> AgentState:
    brief = state["brief"]
    image_paths = state["image_paths"]
    output_dir = state["output_dir"]
    prompt_map = state["prompt_map"]
    rendered: Dict[str, Dict[str, str]] = {}

    source_image = None
    if image_paths:
        source_image = Image.open(image_paths[0]).convert("RGB")

    font = ImageFont.load_default()
    for product in brief.products:
        product_slug = product.lower().replace(" ", "_")
        product_dir = output_dir / product_slug
        product_dir.mkdir(parents=True, exist_ok=True)
        rendered[product] = {}

        for aspect_name, size in ASPECTS.items():
            if source_image:
                canvas = source_image.resize(size)
            else:
                palette = brief.color_palette or ["#1f3a8a", "#0f172a"]
                base = Image.new("RGB", size, palette[0])
                overlay = Image.new("RGB", size, palette[-1])
                canvas = Image.blend(base, overlay, alpha=0.33)

            draw = ImageDraw.Draw(canvas)
            headline = textwrap.fill(brief.campaign_message, width=28)
            subtitle = textwrap.fill(prompt_map[product], width=48)
            draw.rectangle([(32, 32), (size[0] - 32, size[1] // 2)], fill=(0, 0, 0, 140))
            draw.multiline_text((56, 56), headline, fill="white", font=font, spacing=6)
            draw.multiline_text(
                (56, 180), f"Product: {product}\n{subtitle}", fill="white", font=font, spacing=5
            )
            draw.rectangle(
                [(56, size[1] - 120), (380, size[1] - 64)],
                fill=(255, 255, 255),
            )
            draw.text((74, size[1] - 104), "Shop now", fill=(0, 0, 0), font=font)

            filename = f"{product_slug}_{aspect_name}.png"
            output_path = product_dir / filename
            canvas.save(output_path, format="PNG")
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
