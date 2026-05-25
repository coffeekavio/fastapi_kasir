from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from database import get_db

router = APIRouter(prefix="/api/stock-opname", tags=["Stok Opname"])

class StockOpnameItemInput(BaseModel):
    ingredient_id: str
    system_stock: float
    physical_stock: float
    difference: float
    cost: int

class StockOpnameCreate(BaseModel):
    cafe_id: str
    total_value: float
    notes: Optional[str] = ""
    items: List[StockOpnameItemInput]

@router.post("/save")
def save_stock_opname(payload: StockOpnameCreate, db: Session = Depends(get_db)):
    try:
        # 1. Simpan header stok opname
        insert_so_query = text("""
            INSERT INTO stock_opnames (cafe_id, total_value, notes, created_at)
            VALUES (:cafe_id, :total_value, :notes, NOW())
            RETURNING id
        """)
        
        so_result = db.execute(insert_so_query, {
            "cafe_id": payload.cafe_id,
            "total_value": payload.total_value,
            "notes": payload.notes
        }).fetchone()
        
        so_id = so_result[0]

        # 2. Simpan detail item dan Update stok gudang (ingredients)
        insert_item_query = text("""
            INSERT INTO stock_opname_items (stock_opname_id, ingredient_id, system_stock, physical_stock, difference, cost)
            VALUES (:stock_opname_id, :ingredient_id, :system_stock, :physical_stock, :difference, :cost)
        """)
        
        update_ingredient_query = text("""
            UPDATE ingredients
            SET stock = :stock
            WHERE id = :id
        """)
        
        for item in payload.items:
            # Simpan riwayat
            db.execute(insert_item_query, {
                "stock_opname_id": so_id,
                "ingredient_id": item.ingredient_id,
                "system_stock": item.system_stock,
                "physical_stock": item.physical_stock,
                "difference": item.difference,
                "cost": item.cost
            })
            
            # UPDATE nilai di master gudang menjadi physical_stock
            db.execute(update_ingredient_query, {
                "id": item.ingredient_id,
                "stock": item.physical_stock
            })
        
        db.commit()
        return {"status": "success", "message": "Stok Opname tersimpan dan gudang diperbarui!"}
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Save stock opname error - {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/list/{cafe_id}")
def get_stock_opnames(cafe_id: str, db: Session = Depends(get_db)):
    try:
        query = text("""
            SELECT id, cafe_id, total_value, notes, created_at
            FROM stock_opnames
            WHERE cafe_id = :cafe_id
            ORDER BY created_at DESC
        """)
        results = db.execute(query, {"cafe_id": cafe_id}).mappings().fetchall()
        return {"status": "success", "data": [dict(row) for row in results]}
    except Exception as e:
        print(f"DEBUG: Get stock opnames error - {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/detail/{stock_opname_id}")
def get_stock_opname_detail(stock_opname_id: str, db: Session = Depends(get_db)):
    try:
        # Ambil header stok opname
        so_query = text("""
            SELECT id, cafe_id, total_value, notes, created_at
            FROM stock_opnames
            WHERE id = :id
        """)
        so_result = db.execute(so_query, {"id": stock_opname_id}).mappings().fetchone()
        
        if not so_result:
            raise HTTPException(status_code=404, detail="Stok Opname tidak ditemukan")
        
        # Ambil detail items
        items_query = text("""
            SELECT id, stock_opname_id, ingredient_id, system_stock, physical_stock, difference, cost
            FROM stock_opname_items
            WHERE stock_opname_id = :stock_opname_id
        """)
        items_results = db.execute(items_query, {"stock_opname_id": stock_opname_id}).mappings().fetchall()
        
        return {
            "status": "success",
            "data": {
                "header": dict(so_result),
                "items": [dict(row) for row in items_results]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"DEBUG: Get stock opname detail error - {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))