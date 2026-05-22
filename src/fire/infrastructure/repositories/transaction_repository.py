from datetime import date as Date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from fire.domain.entities.transaction import Transaction, TransactionCategory, TransactionType
from fire.domain.interfaces.repositories import ITransactionRepository
from fire.infrastructure.db.models import TransactionORM


class TransactionRepository(ITransactionRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def save(self, transaction: Transaction) -> Transaction:
        with self._session_factory() as session:
            session.merge(_to_orm(transaction))
            session.commit()
        return transaction

    async def save_batch(self, transactions: list[Transaction]) -> list[Transaction]:
        with self._session_factory() as session:
            for tx in transactions:
                session.merge(_to_orm(tx))
            session.commit()
        return transactions

    async def get_by_id(self, transaction_id: UUID) -> Transaction | None:
        with self._session_factory() as session:
            orm = session.get(TransactionORM, str(transaction_id))
            return _to_entity(orm) if orm else None

    async def get_by_document(self, document_id: UUID) -> list[Transaction]:
        with self._session_factory() as session:
            rows = session.query(TransactionORM).filter_by(document_id=str(document_id)).all()
            return [_to_entity(r) for r in rows]

    async def get_by_user_and_month(
        self, user_id: UUID, year: int, month: int
    ) -> list[Transaction]:
        # ISO date prefix filter: YYYY-MM
        prefix = f"{year:04d}-{month:02d}"
        with self._session_factory() as session:
            rows = (
                session.query(TransactionORM)
                .filter(
                    TransactionORM.user_id == str(user_id),
                    TransactionORM.date.like(f"{prefix}%"),
                )
                .all()
            )
            return [_to_entity(r) for r in rows]

    async def get_all_by_user(self, user_id: UUID) -> list[Transaction]:
        with self._session_factory() as session:
            rows = (
                session.query(TransactionORM)
                .filter_by(user_id=str(user_id))
                .order_by(TransactionORM.date.desc())
                .all()
            )
            return [_to_entity(r) for r in rows]

    async def get_by_transfer_document(self, transfer_document_id: UUID) -> list[Transaction]:
        with self._session_factory() as session:
            rows = (
                session.query(TransactionORM)
                .filter_by(document_id=str(transfer_document_id))
                .order_by(TransactionORM.date.desc())
                .all()
            )
            return [_to_entity(r) for r in rows]

    async def get_transfers_by_user(self, user_id: UUID) -> list[Transaction]:
        with self._session_factory() as session:
            from sqlalchemy import or_

            rows = (
                session.query(TransactionORM)
                .filter(
                    TransactionORM.user_id == str(user_id),
                    or_(
                        TransactionORM.transaction_type == "transfer",
                        TransactionORM.transfer_account_name.isnot(None),
                    ),
                )
                .order_by(TransactionORM.date.desc())
                .all()
            )
            return [_to_entity(r) for r in rows]

    async def get_by_parent(self, parent_transaction_id: UUID) -> list[Transaction]:
        with self._session_factory() as session:
            rows = (
                session.query(TransactionORM)
                .filter_by(parent_transaction_id=str(parent_transaction_id))
                .order_by(TransactionORM.description)
                .all()
            )
            return [_to_entity(r) for r in rows]

    async def delete(self, transaction_id: UUID) -> None:
        with self._session_factory() as session:
            # Cascade: delete receipt items and investment transactions linked to this one
            session.query(TransactionORM).filter_by(
                parent_transaction_id=str(transaction_id)
            ).delete()
            # Also delete any investment transactions from an attached transfer document
            tx = session.query(TransactionORM).filter_by(id=str(transaction_id)).first()
            if tx and tx.transfer_document_id:
                session.query(TransactionORM).filter_by(
                    document_id=tx.transfer_document_id
                ).delete()
            session.query(TransactionORM).filter_by(id=str(transaction_id)).delete()
            session.commit()

    async def get_by_category(
        self,
        user_id: UUID,
        category: TransactionCategory,
        from_date: Date | None = None,
        to_date: Date | None = None,
    ) -> list[Transaction]:
        with self._session_factory() as session:
            query = session.query(TransactionORM).filter(
                TransactionORM.user_id == str(user_id),
                TransactionORM.category == category.value,
            )
            if from_date:
                query = query.filter(TransactionORM.date >= from_date.isoformat())
            if to_date:
                query = query.filter(TransactionORM.date <= to_date.isoformat())
            return [_to_entity(r) for r in query.all()]


def _to_orm(tx: Transaction) -> TransactionORM:
    return TransactionORM(
        id=str(tx.id),
        user_id=str(tx.user_id),
        document_id=str(tx.document_id),
        account_id=str(tx.account_id) if tx.account_id else None,
        date=tx.date.isoformat(),
        description=tx.description,
        amount=str(tx.amount),
        transaction_type=tx.transaction_type.value,
        category=tx.category.value,
        merchant=tx.merchant,
        notes=tx.notes,
        is_recurring=tx.is_recurring,
        parent_transaction_id=str(tx.parent_transaction_id) if tx.parent_transaction_id else None,
        receipt_document_id=str(tx.receipt_document_id) if tx.receipt_document_id else None,
        transfer_account_name=tx.transfer_account_name,
        transfer_document_id=str(tx.transfer_document_id) if tx.transfer_document_id else None,
    )


def _to_entity(orm: TransactionORM) -> Transaction:
    return Transaction(
        id=UUID(orm.id),
        user_id=UUID(orm.user_id),
        document_id=UUID(orm.document_id),
        account_id=UUID(orm.account_id) if orm.account_id else None,
        date=Date.fromisoformat(orm.date),
        description=orm.description,
        amount=Decimal(str(orm.amount)),
        transaction_type=TransactionType(orm.transaction_type),
        category=TransactionCategory(orm.category),
        merchant=orm.merchant,
        notes=orm.notes,
        is_recurring=orm.is_recurring,
        parent_transaction_id=UUID(orm.parent_transaction_id)
        if orm.parent_transaction_id
        else None,
        receipt_document_id=UUID(orm.receipt_document_id) if orm.receipt_document_id else None,
        transfer_account_name=orm.transfer_account_name,
        transfer_document_id=UUID(orm.transfer_document_id) if orm.transfer_document_id else None,
    )
