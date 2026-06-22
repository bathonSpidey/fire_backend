# src/routes/inventory_stats.py
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Absolute path boundaries mapping to your project layout
from database.session import get_db
from services.inventory_analysis import InventoryAnalysis

router = APIRouter(prefix="/inventory-analytics", tags=["Deterministic Analytics Engine"])

# --- Pydantic Presentation Contract Schemas ---

class AnalyticsDashboardResponse(BaseModel):
    rolling_staples: list[dict[str, Any]]
    predicted_pantry_deficits: list[dict[str, Any]]
    regularly_purchased_essentials: list[dict[str, Any]]
    financial_leakage: dict[str, Any]
    price_inflation_alerts: list[dict[str, Any]]


# --- API Endpoint Controllers ---

@router.get("/dashboard", response_model=AnalyticsDashboardResponse, status_code=status.HTTP_200_OK)
def get_comprehensive_inventory_analytics_dashboard(
    rolling_days: int = Query(90, description="The historic window for staples calculation"),
    leakage_days: int = Query(30, description="The window for calculating wasted budget loss"),
    db: Session = Depends(get_db)
):
    """Compiles high-value portfolio metrics, item regularity pacing intervals, 

    inflation alerts, and predictive replenishment tracking without triggering LLM workloads.
    """
    analysis = InventoryAnalysis(db)
    
    return AnalyticsDashboardResponse(
        rolling_staples=analysis.get_rolling_staples(rolling_days=rolling_days),
        predicted_pantry_deficits=analysis.get_predicted_pantry_deficits(),
        regularly_purchased_essentials=analysis.get_regularly_purchased_essentials(),
        financial_leakage=analysis.get_financial_leakage_analysis(rolling_days=leakage_days),
        price_inflation_alerts=analysis.get_price_inflation_alerts()
    )


@router.get("/regular-essentials", status_code=status.HTTP_200_OK)
def get_regular_essentials_only(db: Session = Depends(get_db)):
    """Isolated view to fetch items bought consistently over months, including spacing intervals."""
    analysis = InventoryAnalysis(db)
    return analysis.get_regularly_purchased_essentials()


@router.get("/inflation-ticker", status_code=status.HTTP_200_OK)
def get_inflation_ticker_alerts(db: Session = Depends(get_db)):
    """Isolated ticker track signaling when stores change prices on identical household products."""
    analysis = InventoryAnalysis(db)
    return analysis.get_price_inflation_alerts()