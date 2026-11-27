"""Typed domain schemas for Performance Marketing (`LOW_LEVEL_DESIGN.md` §3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

IntentType = Literal[
    "KPI_SINGLE_OR_TREND",
    "CAMPAIGN_PLAN",
    "LIVE_AD_DIAGNOSTIC",
    "COMPETITOR_INTEL",
    "MEMORY_RECALL",
    "MEMORY_SAVE",
    "WRITE_ACTION_REFUSAL",
]

MarketingCitationSource = Literal[
    "BigQuery",
    "Mixpanel",
    "Meta Ads Account",
    "Google Ads Account",
    "Meta Ad Library",
    "Google Ads Transparency",
    "Smriti Memory",
    "Excel Ruleset",
    "Google Search",
]


class CampaignPlanIntake(BaseModel):
    """Normalized intake parameters for a multi-channel Campaign Brief."""

    product_query: str = Field(..., min_length=1)
    region: str = "All India"
    region_assumed: bool = True
    budget_inr: int = Field(..., gt=0)
    target_roas: float | None = Field(default=None, gt=0)
    target_cac_inr: float | None = Field(default=None, gt=0)
    target_assumed: bool = True
    window_label: str = Field(..., min_length=1)
    external_premise: str | None = None


class BudgetPhaseRow(BaseModel):
    """Single non-overlapping budget allocation row in a phased campaign plan."""

    phase_name: str = Field(..., min_length=1)
    channel: Literal["Meta Ads", "Google Ads", "Blended"]
    funnel_stage: str = Field(..., min_length=3)
    amount_inr: int = Field(..., ge=0)
    daily_run_rate_inr: int = Field(..., ge=0)
    date_range: str = Field(..., min_length=1)
    scale_condition: str = Field(..., min_length=1)

    @field_validator("funnel_stage")
    @classmethod
    def _validate_funnel_stage(cls, value: str) -> str:
        if value == "A/B Test Arm" or value.startswith(("Prospecting (", "Retargeting (")):
            return value
        raise ValueError(f"Invalid funnel_stage '{value}'.")


class PhasedBudgetPlan(BaseModel):
    """Phased budget allocation verified to sum strictly to 100% of total_budget_inr."""

    total_budget_inr: int = Field(..., gt=0)
    scale_multiple_vs_last_closed: float | None = Field(default=None, gt=0)
    rows: list[BudgetPhaseRow] = Field(..., min_length=1)

    @model_validator(mode="after")
    def verify_exact_budget_sum(self) -> PhasedBudgetPlan:
        allocated = sum(
            row.amount_inr for row in self.rows if row.funnel_stage != "A/B Test Arm"
        )
        if allocated != self.total_budget_inr:
            raise ValueError(
                f"Allocated Rs {allocated} != Total Budget Rs {self.total_budget_inr}"
            )
        return self
