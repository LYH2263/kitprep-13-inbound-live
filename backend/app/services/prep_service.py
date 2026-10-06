"""Prep sheet computation shared by the prep API and inventory inbound.

A PrepRun stores a full-text snapshot (result_json). Only the newest run per
order is a living document: stock changes rewrite it in place. Older runs are
archived history and are never touched here.
"""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import BomLine, Ingredient, KitchenOrder, OrderLine, PrepRun
from app.services.bom_engine import explode_and_merge, result_to_dict


def compute_prep_result(db: Session, order: KitchenOrder) -> dict:
    """Explode the order's lines against current stock into a prep-sheet dict."""
    ols = [{"dish_id": l.dish_id, "portions": l.portions}
           for l in db.scalars(select(OrderLine).where(OrderLine.order_id == order.id)).all()]
    bom = [{"dish_id": b.dish_id, "ingredient_id": b.ingredient_id, "qty_per_portion": b.qty_per_portion}
           for b in db.scalars(select(BomLine)).all()]
    ings = {i.id: {"code": i.code, "name": i.name, "unit": i.unit, "stock_qty": i.stock_qty}
            for i in db.scalars(select(Ingredient)).all()}
    result = result_to_dict(explode_and_merge(ols, bom, ings))
    result["order"] = {"id": order.id, "code": order.code, "outlet": order.outlet}
    return result


def refresh_latest_prep_runs(db: Session) -> int:
    """Recompute the newest PrepRun of every order against current stock.

    Older (archived) runs keep their original full text. The caller owns the
    transaction: this only stages updates, so a failure anywhere rolls back
    the stock change and the sheet refresh together.
    """
    refreshed = 0
    order_ids = db.scalars(select(PrepRun.order_id).distinct()).all()
    for oid in order_ids:
        run = db.scalars(
            select(PrepRun)
            .where(PrepRun.order_id == oid)
            .order_by(PrepRun.id.desc())
            .limit(1)
        ).first()
        order = db.get(KitchenOrder, oid)
        if run is None or order is None:
            continue
        run.result_json = json.dumps(compute_prep_result(db, order), ensure_ascii=False)
        refreshed += 1
    return refreshed
