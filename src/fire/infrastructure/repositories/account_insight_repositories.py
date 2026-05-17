import json
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from src.fire.domain.entities.account import Account, AccountType
from src.fire.domain.entities.budget_insight import BudgetInsight, SpendingBreakdown
from src.fire.domain.interfaces.repositories import IAccountRepository, IInsightRepository
from src.fire.infrastructure.db.models import AccountORM, InsightORM


class AccountRepository(IAccountRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def save(self, account: Account) -> Account:
        with self._session_factory() as session:
            session.merge(_account_to_orm(account))
            session.commit()
        return account

    async def get_by_id(self, account_id: UUID) -> Account | None:
        with self._session_factory() as session:
            orm = session.get(AccountORM, str(account_id))
            return _account_to_entity(orm) if orm else None

    async def list_by_user(self, user_id: UUID) -> list[Account]:
        with self._session_factory() as session:
            rows = session.query(AccountORM).filter_by(user_id=str(user_id), is_active=True).all()
            return [_account_to_entity(r) for r in rows]

    async def update(self, account: Account) -> Account:
        with self._session_factory() as session:
            session.merge(_account_to_orm(account))
            session.commit()
        return account


class InsightRepository(IInsightRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def save(self, insight: BudgetInsight) -> BudgetInsight:
        with self._session_factory() as session:
            # upsert: delete existing for same user+year+month then insert
            session.query(InsightORM).filter_by(
                user_id=str(insight.user_id), year=insight.year, month=insight.month
            ).delete()
            session.add(_insight_to_orm(insight))
            session.commit()
        return insight

    async def get_by_user_and_month(
        self, user_id: UUID, year: int, month: int
    ) -> BudgetInsight | None:
        with self._session_factory() as session:
            orm = (
                session.query(InsightORM)
                .filter_by(user_id=str(user_id), year=year, month=month)
                .first()
            )
            return _insight_to_entity(orm) if orm else None

    async def list_by_user(self, user_id: UUID, limit: int = 12) -> list[BudgetInsight]:
        with self._session_factory() as session:
            rows = (
                session.query(InsightORM)
                .filter_by(user_id=str(user_id))
                .order_by(InsightORM.year.desc(), InsightORM.month.desc())
                .limit(limit)
                .all()
            )
            return [_insight_to_entity(r) for r in rows]


# ── Account mappers ──────────────────────────────────────────────────────────


def _account_to_orm(account: Account) -> AccountORM:
    return AccountORM(
        id=str(account.id),
        user_id=str(account.user_id),
        name=account.name,
        account_type=account.account_type.value,
        institution=account.institution,
        last_known_balance=str(account.last_known_balance) if account.last_known_balance else None,
        currency=account.currency,
        is_active=account.is_active,
    )


def _account_to_entity(orm: AccountORM) -> Account:
    return Account(
        id=UUID(orm.id),
        user_id=UUID(orm.user_id),
        name=orm.name,
        account_type=AccountType(orm.account_type),
        institution=orm.institution,
        last_known_balance=Decimal(str(orm.last_known_balance)) if orm.last_known_balance else None,
        currency=orm.currency,
        is_active=orm.is_active,
    )


# ── Insight mappers ──────────────────────────────────────────────────────────


def _insight_to_orm(insight: BudgetInsight) -> InsightORM:
    breakdown_data = [
        {
            "category": b.category,
            "total": str(b.total),
            "transaction_count": b.transaction_count,
            "percentage_of_spend": str(b.percentage_of_spend),
        }
        for b in insight.spending_breakdown
    ]
    return InsightORM(
        id=str(insight.id),
        user_id=str(insight.user_id),
        year=insight.year,
        month=insight.month,
        total_income=str(insight.total_income),
        total_expenses=str(insight.total_expenses),
        net_savings=str(insight.net_savings),
        savings_rate=str(insight.savings_rate),
        spending_breakdown=json.dumps(breakdown_data),
        llm_summary=insight.llm_summary,
        llm_tips=json.dumps(insight.llm_tips),
        generated_at=insight.generated_at,
        fire_progress_note=insight.fire_progress_note,
    )


def _insight_to_entity(orm: InsightORM) -> BudgetInsight:
    breakdown_data = json.loads(orm.spending_breakdown)
    breakdown = [
        SpendingBreakdown(
            category=b["category"],
            total=Decimal(b["total"]),
            transaction_count=b["transaction_count"],
            percentage_of_spend=Decimal(b["percentage_of_spend"]),
        )
        for b in breakdown_data
    ]
    return BudgetInsight(
        id=UUID(orm.id),
        user_id=UUID(orm.user_id),
        year=orm.year,
        month=orm.month,
        total_income=Decimal(str(orm.total_income)),
        total_expenses=Decimal(str(orm.total_expenses)),
        net_savings=Decimal(str(orm.net_savings)),
        savings_rate=Decimal(str(orm.savings_rate)),
        spending_breakdown=breakdown,
        llm_summary=orm.llm_summary,
        llm_tips=json.loads(orm.llm_tips),
        generated_at=orm.generated_at,
        fire_progress_note=orm.fire_progress_note,
    )
