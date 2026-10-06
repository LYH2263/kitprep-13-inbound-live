from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session
import math
from app.database import get_db
from app.models.models import Ingredient, StockReceipt

router = APIRouter(prefix="/inventory", tags=["inventory"])

class InboundLine(BaseModel):
    ingredient_id: int | None = None
    ingredient_code: str | None = None
    qty: float = Field(...)

class InboundRequest(BaseModel):
    lines: list[InboundLine]

def _serialize(r: Ingredient) -> dict:
    return {"id": r.id, "code": r.code, "name": r.name, "unit": r.unit, "stock_qty": r.stock_qty}

@router.get("")
def list_inventory(db: Session = Depends(get_db)):
    return [_serialize(r) for r in db.scalars(select(Ingredient).order_by(Ingredient.id)).all()]

@router.post("/inbound")
def inbound(req: InboundRequest, db: Session = Depends(get_db)):
    """入库：结存与入库流水在同一事务内一起提交。

    数量为负/零、原料对不上号（id 与编码缺失、互不一致或不存在）一律 400，
    此时结存和流水都不动 —— 要么整单过，要么整单停。
    """
    if not req.lines:
        raise HTTPException(400, "入库明细不能为空")
    try:
        # 1) 先整单校验，任何一行不合法都不写库
        targets: list[tuple[Ingredient, float]] = []
        for idx, line in enumerate(req.lines):
            if line.qty is None or not math.isfinite(line.qty) or line.qty <= 0:
                raise HTTPException(400, f"第{idx + 1}行入库数量必须为正数，收到 {line.qty}")
            if line.ingredient_id is None and not line.ingredient_code:
                raise HTTPException(400, f"第{idx + 1}行缺少原料标识（id 或编码）")
            ing: Ingredient | None = None
            if line.ingredient_id is not None:
                ing = db.get(Ingredient, line.ingredient_id)
                if ing is None:
                    raise HTTPException(400, f"第{idx + 1}行原料 id={line.ingredient_id} 不存在")
            if line.ingredient_code:
                by_code = db.scalars(
                    select(Ingredient).where(Ingredient.code == line.ingredient_code)
                ).first()
                if by_code is None:
                    raise HTTPException(400, f"第{idx + 1}行原料编码 {line.ingredient_code} 不存在")
                if ing is not None and by_code.id != ing.id:
                    raise HTTPException(
                        400,
                        f"第{idx + 1}行原料对不上号：id={ing.id}({ing.code}) 与编码 {line.ingredient_code}",
                    )
                ing = by_code
            targets.append((ing, float(line.qty)))

        # 2) 全部合法：结存用数据库原子自增（并发入库不丢量），流水落账，同一事务提交
        totals: dict[int, float] = {}
        receipts: list[StockReceipt] = []
        for ing, qty in targets:
            totals[ing.id] = totals.get(ing.id, 0.0) + qty
            receipts.append(StockReceipt(ingredient_id=ing.id, qty=qty))
        for iid, total in totals.items():
            db.execute(
                update(Ingredient).where(Ingredient.id == iid)
                .values(stock_qty=Ingredient.stock_qty + total)
            )
        for rcpt in receipts:
            db.add(rcpt)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    for rcpt in receipts:
        db.refresh(rcpt)
    return {
        "receipt_ids": [r.id for r in receipts],
        "inventory": [
            _serialize(r)
            for r in db.scalars(select(Ingredient).order_by(Ingredient.id)).all()
        ],
    }
