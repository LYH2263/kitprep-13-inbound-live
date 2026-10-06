from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Ingredient
from app.services.prep_service import refresh_latest_prep_runs
router = APIRouter(prefix="/inventory", tags=["inventory"])

@router.get("")
def list_inventory(db: Session = Depends(get_db)):
    return [{"id": r.id, "code": r.code, "name": r.name, "unit": r.unit, "stock_qty": r.stock_qty}
            for r in db.scalars(select(Ingredient).order_by(Ingredient.id)).all()]

class InboundIn(BaseModel):
    ingredient_id: int | None = None
    code: str | None = None
    qty: float = Field(gt=0, allow_inf_nan=False)

@router.post("/inbound")
def inbound(payload: InboundIn, db: Session = Depends(get_db)):
    """Stock-in against current balance. Stock, the latest prep sheet's lines
    and the shortage-sticky count move in one transaction: all three or none."""
    ing = None
    if payload.ingredient_id is not None:
        ing = db.get(Ingredient, payload.ingredient_id)
    if ing is None and payload.code:
        ing = db.scalars(select(Ingredient).where(Ingredient.code == payload.code)).first()
    if ing is None:
        raise HTTPException(404, "原料不存在")
    ing.stock_qty = round(ing.stock_qty + payload.qty, 3)
    db.flush()
    refreshed = refresh_latest_prep_runs(db)
    db.commit()
    return {"id": ing.id, "code": ing.code, "name": ing.name, "unit": ing.unit,
            "stock_qty": ing.stock_qty, "refreshed_runs": refreshed}
