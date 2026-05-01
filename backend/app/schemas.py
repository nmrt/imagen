from __future__ import annotations

from typing import Dict, List
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class CampaignBrief(BaseModel):
    campaign_id: str
    products: List[str] = Field(min_length=2)
    target_region: str
    target_audience: str
    campaign_message: str
    color_palette: List[str] = Field(default_factory=list)

    @field_validator("products")
    @classmethod
    def validate_products(cls, value: List[str]) -> List[str]:
        unique = list(dict.fromkeys(v.strip() for v in value if v and v.strip()))
        if len(unique) < 2:
            raise ValueError("products must include at least two distinct entries")
        return unique


class ProductResult(BaseModel):
    product: str
    images: Dict[str, str]


class GenerationResult(BaseModel):
    run_id: UUID
    campaign_id: str
    products: List[ProductResult]
    zip_path: str
    manifest_path: str
