from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.session import get_db
from services import linking

router = APIRouter(prefix="/reviews", tags=["Review Questions"])


class AnswerIn(BaseModel):
    answer: Literal["yes", "no"]


@router.get("")
def list_open_questions(db: Session = Depends(get_db)) -> list[dict]:
    """Yes/no questions Claude could not settle on its own."""
    return linking.open_questions(db)


@router.post("/{question_id}/answer")
def answer_question(question_id: int, body: AnswerIn, db: Session = Depends(get_db)) -> dict:
    result = linking.answer_question(db, question_id, yes=body.answer == "yes")
    if not result.ok:
        raise HTTPException(status.HTTP_409_CONFLICT, result.message)
    return {"message": result.message}
