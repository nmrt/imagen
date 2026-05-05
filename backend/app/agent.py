from __future__ import annotations

import math
import mimetypes
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Dict, List
from typing_extensions import TypedDict
from pydantic import TypeAdapter

from google import genai
from google.genai import types as genai_types
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from vertexai import init as vertex_init
from vertexai.preview.vision_models import Image, ImageGenerationModel

from .schemas import CampaignBrief


ASPECTS: Dict[str, str] = {
    "1x1": "1:1",
    "9x16": "9:16",
    "16x9": "16:9",
}

_IMAGEN_CALL_KW: Dict[str, object] = {
    "negative_prompt": "",
    "number_of_images": 1,
    "guidance_scale": 7,
    "safety_filter_level": "block_some",
    "person_generation": "allow_adult",
}


def _guess_mime_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if mime and mime.startswith("image/"):
        return mime
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "image/jpeg")


def _compose_render_prompt(
    brief: CampaignBrief,
    product: str,
    prompt_map: Dict[str, str],
    source_context: str,
) -> str:
    return (
        f"{prompt_map[product]} "
        f"Use brand colors {brief.color_palette}. "
        f"{source_context}. "
        "Create a social ad background with clean composition and realistic lighting. "
        "Leave clear negative space for headline and CTA overlay. "
        "Localize the message to the target region."
    )


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
        model_name = os.getenv("VERTEX_IMAGEN_MODEL", "imagen-4.0-generate-001") # imagen-3.0-generate-002

        print(f"Project: {project}, Location: {location}, Model: {model_name}")

        if not project:
            raise RuntimeError("Set VERTEX_PROJECT_ID before generating with Imagen.")

        vertex_init(project=project, location=location)
        self.model = ImageGenerationModel.from_pretrained(model_name)

    def generate(
        self,
        prompt: str,
        aspect_ratio: str,
        output_path: Path,
        *,
        base_image_paths: Sequence[Path] | None = None,
    ) -> None:
        paths = list(base_image_paths or ())
        base_image_path = paths[0] if paths else None
        print(f"ImagenClient.generate: {prompt}")
        print(
            f"aspect_ratio: {aspect_ratio}, "
            f"output_path: {output_path}, base_image_path: {base_image_path}"
        )

        # if base_image_path is not None:
        #     base_img = Image.load_from_file(str(base_image_path))
        #     # mask_img = self.model.generateMaskAndPadForOutpainting(
        #     #     image=base_img,
        #     #     target_width=1920,
        #     #     target_height=1080
        #     # )
        #     result = self.model.edit_image(
        #         prompt=prompt,
        #         base_image=base_img,
        #         # mask=mask_img,
        #         edit_mode="outpainting",
        #         # mask_mode="MASK_MODE_BACKGROUND",
        #         mask_mode="background",
        #         mask_dilation=0.03,
        #         **_IMAGEN_CALL_KW,
        #     )
        # else:
        result = self.model.generate_images(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            **_IMAGEN_CALL_KW,
        )
        if not result.images:
            raise RuntimeError("Imagen returned no images.")
        result.images[0].save(location=str(output_path))


class GeminiImageClient:
    """Gemini image generation on Vertex AI via the google-genai SDK."""

    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            self._client = genai.Client(api_key=api_key)
        else:
            project = os.getenv("VERTEX_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
            location = os.getenv("GEMINI_LOCATION") or os.getenv("VERTEX_GEMINI_LOCATION") or "global"
            print(f"GeminiImageClient: project={project}, location={location}")
            self._client = genai.Client(vertexai=True, project=project, location=location)
        self._model = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3-pro-image-preview")
        print(f"GeminiImageClient: model={self._model}")
    def generate(
        self,
        prompt: str, 
        aspect_ratio: str, 
        output_path: Path, 
        *, 
        base_image_paths: Sequence[Path] | None = None,
    ) -> None:
        print(
            f"GeminiImageClient.generate: aspect_ratio={aspect_ratio}, "
            f"output_path={output_path}, reference_images={list(base_image_paths or ())}"
        )
        parts: List[genai_types.Part] = []
        for p in base_image_paths or ():
            path = Path(p)
            parts.append(
                genai_types.Part(
                    inline_data=genai_types.Blob(
                        mime_type=_guess_mime_type(path),
                        data=path.read_bytes(),
                    )
                )
            )
        parts.append(genai_types.Part(text=prompt))
        contents = [genai_types.Content(role="user", parts=parts)]
        config = genai_types.GenerateContentConfig(
            response_modalities=[
                genai_types.Modality.TEXT,
                genai_types.Modality.IMAGE,
            ],
            image_config=genai_types.ImageConfig(aspect_ratio=aspect_ratio),
        )
        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=config,
        )
        if not response.candidates:
            raise RuntimeError("Gemini returned no candidates.")
        for cand in response.candidates:
            content = cand.content
            if not content or not content.parts:
                continue
            for part in content.parts:
                inline = part.inline_data
                if inline is not None and inline.data:
                    output_path.write_bytes(bytes(inline.data))
                    return
        raise RuntimeError("Gemini returned no image data.")


def _image_generation_client() -> ImagenClient | GeminiImageClient:
    backend = os.getenv("IMAGE_GEN_BACKEND", "imagen").strip().lower()
    if backend == "gemini":
        return GeminiImageClient()
    return ImagenClient()


def _render_images(state: AgentState) -> AgentState:
    adapter = TypeAdapter(AgentState)
    print(f"_render_images state: {adapter.dump_json(state, indent=2).decode('utf-8')}")

    brief = state["brief"]
    output_dir = state["output_dir"]
    prompt_map = state["prompt_map"]
    source_context = state["source_context"]
    rendered: Dict[str, Dict[str, str]] = {}

    client = _image_generation_client()
    for product in brief.products:
        product_slug = product.lower().replace(" ", "_")
        product_dir = output_dir / product_slug
        product_dir.mkdir(parents=True, exist_ok=True)
        rendered[product] = {}

        for aspect_name, aspect_ratio in ASPECTS.items():
            filename = f"{product_slug}_{aspect_name}.png"
            output_path = product_dir / filename
            prompt = _compose_render_prompt(brief, product, prompt_map, source_context)
            client.generate(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                output_path=output_path,
                base_image_paths=state["image_paths"],
            )
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
