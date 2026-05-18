from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from fire.api.dependencies import get_transaction_repo
from fire.api.schemas.transaction import PatchTransactionRequest, TransactionResponse
from fire.domain.entities.transaction import Transaction
from fire.infrastructure.repositories.transaction_repository import TransactionRepository

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=list[TransactionResponse])
async def list_transactions(
    user_id: UUID,
    year: int | None = None,
    month: int | None = None,
    transaction_repo: TransactionRepository = Depends(get_transaction_repo),
) -> list[TransactionResponse]:
    """
    List transactions for a user.
    - Provide year + month to filter to a specific month.
    - Omit both to get all transactions.
    """
    if year is not None and month is not None:
        transactions = await transaction_repo.get_by_user_and_month(user_id, year, month)
    else:
        transactions = await transaction_repo.get_all_by_user(user_id)
    return [_to_response(t) for t in transactions]


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: UUID,
    transaction_repo: TransactionRepository = Depends(get_transaction_repo),
) -> TransactionResponse:
    transaction = await transaction_repo.get_by_id(transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _to_response(transaction)


@router.patch("/{transaction_id}", response_model=TransactionResponse)
async def patch_transaction(
    transaction_id: UUID,
    request: PatchTransactionRequest,
    transaction_repo: TransactionRepository = Depends(get_transaction_repo),
) -> TransactionResponse:
    """Correct a transaction after extraction. Only provided fields are updated."""
    transaction = await transaction_repo.get_by_id(transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if request.amount is not None:
        transaction.amount = request.amount
    if request.transaction_type is not None:
        transaction.transaction_type = request.transaction_type
    if request.category is not None:
        transaction.category = request.category
    if request.description is not None:
        transaction.description = request.description
    if request.merchant is not None:
        transaction.merchant = request.merchant
    if request.notes is not None:
        transaction.notes = request.notes
    if request.is_recurring is not None:
        transaction.is_recurring = request.is_recurring

    updated = await transaction_repo.save(transaction)
    return _to_response(updated)


@router.delete("/{transaction_id}", status_code=204)
async def delete_transaction(
    transaction_id: UUID,
    transaction_repo: TransactionRepository = Depends(get_transaction_repo),
) -> None:
    transaction = await transaction_repo.get_by_id(transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    await transaction_repo.delete(transaction_id)


def _to_response(t: Transaction) -> TransactionResponse:
    return TransactionResponse(
        id=t.id,
        user_id=t.user_id,
        document_id=t.document_id,
        date=t.date,
        description=t.description,
        amount=t.amount,
        transaction_type=t.transaction_type,
        category=t.category,
        merchant=t.merchant,
        notes=t.notes,
        is_recurring=t.is_recurring,
    )
