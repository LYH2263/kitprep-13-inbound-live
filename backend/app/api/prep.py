import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import BomLine, Ingredient, KitchenOrder, OrderLine, PrepRun
from app.services.bom_engine import explode_and_merge, project_with_live_stock, result_to_dict
router = APIRouter(prefix="/prep", tags=["prep"])

def _live_ingredients(db: Session) -> dict:
    return {i.id: {"code": i.code, "name": i.name, "unit": i.unit, "stock_qty": i.stock_qty}
            for i in db.scalars(select(Ingredient)).all()}

@router.post("/run")
def run_prep(order_id: int = 1, db: Session = Depends(get_db)):
    order = db.get(KitchenOrder, order_id)
    if not order: raise HTTPException(404, "订单不存在")
    ols = [{"dish_id": l.dish_id, "portions": l.portions}
           for l in db.scalars(select(OrderLine).where(OrderLine.order_id == order_id)).all()]
    bom = [{"dish_id": b.dish_id, "ingredient_id": b.ingredient_id, "qty_per_portion": b.qty_per_portion}
           for b in db.scalars(select(BomLine)).all()]
    ings = _live_ingredients(db)
    result = result_to_dict(explode_and_merge(ols, bom, ings))
    result["order"] = {"id": order.id, "code": order.code, "outlet": order.outlet}
    run = PrepRun(order_id=order_id, created_at=datetime.utcnow(), result_json=json.dumps(result, ensure_ascii=False))
    db.add(run); db.commit(); db.refresh(run)
    return {"id": run.id, **result}

@router.get("/latest")
def latest(order_id: int = 1, db: Session = Depends(get_db)):
    """最新备料单：需求取自存档快照，库存/每行缺料/缺料张数按当前结存实时重算。

    存档行（result_json）不被改写；已存档的旧备料单仍可通过 /prep/runs/{id} 查看原样。
    """
    run = db.scalars(select(PrepRun).where(PrepRun.order_id == order_id).order_by(PrepRun.id.desc())).first()
    if not run:
        return run_prep(order_id=order_id, db=db)
    snapshot = json.loads(run.result_json)
    projected = project_with_live_stock(snapshot, _live_ingredients(db))
    return {"id": run.id, "archived_at": run.created_at.isoformat() if run.created_at else None, **projected}

@router.get("/shortages")
def shortages(order_id: int = 1, db: Session = Depends(get_db)):
    data = latest(order_id=order_id, db=db)
    return {"order_id": order_id, "shortages": data.get("shortages", []), "stats": data.get("stats", {})}

@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    """查看已存档备料单原文：返回生成那一刻的完整快照，不受后续入库影响。"""
    run = db.get(PrepRun, run_id)
    if not run:
        raise HTTPException(404, "备料单不存在")
    data = json.loads(run.result_json)
    return {"id": run.id, "order_id": run.order_id,
            "archived_at": run.created_at.isoformat() if run.created_at else None,
            "stock_live": False, **data}
