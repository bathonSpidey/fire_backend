import json
from decimal import Decimal

import httpx

from src.fire.domain.interfaces.services import ILLMInsightGenerator

_INSIGHT_PROMPT_TEMPLATE = """
You are a personal finance coach helping someone achieve Financial Independence and Early Retirement (FIRE).

Here is their financial summary for {month_name} {year}:
- Total income:   €{total_income}
- Total expenses: €{total_expenses}
- Net savings:    €{net_savings}
- Savings rate:   {savings_rate:.1f}%

Spending breakdown:
{breakdown}

Write a concise monthly summary (2-3 sentences) and exactly 3 actionable tips to help them
reach FIRE faster. Be specific, encouraging, and reference their actual numbers.

Respond ONLY with a valid JSON object — no markdown, no explanation.

{{
  "summary": "string",
  "tips": ["tip 1", "tip 2", "tip 3"]
}}
"""

_MONTH_NAMES = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


class OllamaInsightGenerator(ILLMInsightGenerator):
    """
    Calls a local Ollama text model to generate monthly financial insights.
    Uses a smaller, faster model than the vision parser since no images needed.

    Recommended: mistral:7b-instruct or llama3.2:3b
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3:14b-q4_K_M",
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._timeout = timeout

    async def generate_monthly_insight(
        self,
        year: int,
        month: int,
        total_income: Decimal,
        total_expenses: Decimal,
        category_totals: dict[str, Decimal],
    ) -> tuple[str, list[str]]:
        net_savings = total_income - total_expenses
        savings_rate = float(net_savings / total_income * 100) if total_income > 0 else 0.0
        breakdown = (
            "\n".join(
                f"  - {cat.replace('_', ' ').title()}: €{amt}"
                for cat, amt in sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
            )
            or "  No expense data available."
        )

        prompt = _INSIGHT_PROMPT_TEMPLATE.format(
            month_name=_MONTH_NAMES[month],
            year=year,
            total_income=total_income,
            total_expenses=total_expenses,
            net_savings=net_savings,
            savings_rate=savings_rate,
            breakdown=breakdown,
        )

        payload = {"model": self._model, "prompt": prompt, "stream": False}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._base_url}/api/generate", json=payload)
            response.raise_for_status()

        raw_text = response.json()["response"]
        return self._parse_response(raw_text)

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/api/tags")
                return response.status_code == 200
        except httpx.ConnectError:
            return False

    @staticmethod
    def _parse_response(raw_text: str) -> tuple[str, list[str]]:
        try:
            start = raw_text.find("{")
            end = raw_text.rfind("}") + 1
            clean = raw_text[start:end] if start != -1 else raw_text
            data = json.loads(clean)
            summary = data.get("summary", raw_text[:300])
            tips = data.get("tips", [])
            if isinstance(tips, list):
                return summary, [str(t) for t in tips[:5]]
        except (json.JSONDecodeError, KeyError):
            pass
        # Graceful fallback — return raw text as summary
        return raw_text[:500], []
