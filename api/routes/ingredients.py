from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from database import get_db

router = APIRouter(prefix="/api/ingredients", tags=["Bahan Baku"])

class IngredientCreate(BaseModel):
    cafe_id: str
    name: str = Field(..., min_length=2)
    stock: float
    unit: str
    cost: int = 0

class IngredientUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2)
    stock: Optional[float] = None
    unit: Optional[str] = None
    cost: Optional[int] = None

@router.get("/")
def get_ingredients(cafe_id: str, db: Session = Depends(get_db)):
    try:
        query = text("""
            SELECT id, cafe_id, name, stock, unit, cost, created_at
            FROM ingredients
            WHERE cafe_id = :cafe_id
            ORDER BY created_at DESC
        """)
        results = db.execute(query, {"cafe_id": cafe_id}).mappings().fetchall()
        return {"status": "success", "data": [dict(row) for row in results]}
    except Exception as e:
        print(f"DEBUG: Get ingredients error - {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/")
def create_ingredient(payload: IngredientCreate, db: Session = Depends(get_db)):
    try:
        insert_query = text("""
            INSERT INTO ingredients (cafe_id, name, stock, unit, cost, created_at)
            VALUES (:cafe_id, :name, :stock, :unit, :cost, NOW())
            RETURNING id, cafe_id, name, stock, unit, cost, created_at
        """)
        result = db.execute(insert_query, {
            "cafe_id": payload.cafe_id,
            "name": payload.name,
            "stock": payload.stock,
            "unit": payload.unit,
            "cost": payload.cost
        }).mappings().fetchone()
        
        db.commit()
        return {"status": "success", "data": dict(result) if result else None}
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Create ingredient error - {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{ingredient_id}")
def update_ingredient(ingredient_id: str, payload: IngredientUpdate, db: Session = Depends(get_db)):
    try:
        # Build dynamic update query
        update_fields = {}
        if payload.name is not None:
            update_fields["name"] = payload.name
        if payload.stock is not None:
            update_fields["stock"] = payload.stock
        if payload.unit is not None:
            update_fields["unit"] = payload.unit
        if payload.cost is not None:
            update_fields["cost"] = payload.cost
        
        if not update_fields:
            raise HTTPException(status_code=400, detail="Tidak ada data yang diperbarui")
        
        set_clause = ", ".join([f"{key} = :{key}" for key in update_fields.keys()])
        update_query = text(f"""
            UPDATE ingredients
            SET {set_clause}
            WHERE id = :id
            RETURNING id, cafe_id, name, stock, unit, cost, created_at
        """)
        
        update_fields["id"] = ingredient_id
        result = db.execute(update_query, update_fields).mappings().fetchone()
        db.commit()
        
        if not result:
            raise HTTPException(status_code=404, detail="Ingredient tidak ditemukan")
        
        return {"status": "success", "data": dict(result)}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Update ingredient error - {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{ingredient_id}")
def delete_ingredient(ingredient_id: str, db: Session = Depends(get_db)):
    try:
        delete_query = text("DELETE FROM ingredients WHERE id = :id")
        result = db.execute(delete_query, {"id": ingredient_id})
        db.commit()
        
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Ingredient tidak ditemukan")
        
        return {"status": "success", "message": "Bahan baku dihapus"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Delete ingredient error - {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))