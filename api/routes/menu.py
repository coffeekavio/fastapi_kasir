from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List
from database import get_db

router = APIRouter(prefix="/api/menus", tags=["Menu Produk"])

# Skema Pydantic
class RecipeInput(BaseModel):
    ingredient_id: str
    quantity: float

class CreateMenuRequest(BaseModel):
    cafe_id: str
    category_id: str
    name: str = Field(..., min_length=2)
    description: Optional[str] = None
    price: int
    is_available: bool = True
    track_stock: bool = False
    recipe: Optional[List[RecipeInput]] = []

class UpdateMenuRequest(BaseModel):
    category_id: Optional[str] = None
    name: Optional[str] = Field(None, min_length=2)
    description: Optional[str] = None
    price: Optional[int] = None
    is_available: Optional[bool] = None
    track_stock: Optional[bool] = None
    recipe: Optional[List[RecipeInput]] = None

@router.get("/")
def get_all_menus(cafe_id: str, db: Session = Depends(get_db)):
    try:
        # Mengambil menu
        query = text("""
            SELECT id, cafe_id, category_id, name, description, price, is_available, track_stock, created_at
            FROM menus
            WHERE cafe_id = :cafe_id
            ORDER BY created_at DESC
        """)
        menus = db.execute(query, {"cafe_id": cafe_id}).mappings().fetchall()
        
        result = []
        for menu in menus:
            menu_dict = dict(menu)
            # Jika track_stock aktif, ambil resepnya
            if menu_dict.get("track_stock"):
                recipe_query = text("""
                    SELECT ingredient_id, quantity
                    FROM recipe_ingredients
                    WHERE menu_id = :menu_id
                """)
                recipes = db.execute(recipe_query, {"menu_id": menu_dict["id"]}).mappings().fetchall()
                menu_dict["recipe"] = [dict(r) for r in recipes]
            else:
                menu_dict["recipe"] = []
            result.append(menu_dict)
        
        return {"status": "success", "data": result}
    except Exception as e:
        print(f"DEBUG: Get menus error - {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/create-menus")
def create_menu(payload: CreateMenuRequest, db: Session = Depends(get_db)):
    try:
        # 1. Simpan Menu Utama
        insert_menu_query = text("""
            INSERT INTO menus (cafe_id, category_id, name, description, price, is_available, track_stock, created_at)
            VALUES (:cafe_id, :category_id, :name, :description, :price, :is_available, :track_stock, NOW())
            RETURNING id
        """)
        
        menu_result = db.execute(insert_menu_query, {
            "cafe_id": payload.cafe_id,
            "category_id": payload.category_id,
            "name": payload.name,
            "description": payload.description,
            "price": payload.price,
            "is_available": payload.is_available,
            "track_stock": payload.track_stock
        }).fetchone()
        
        new_menu_id = menu_result[0]

        # 2. Jika Lacak Stok aktif, simpan Resepnya
        if payload.track_stock and payload.recipe:
            insert_recipe_query = text("""
                INSERT INTO recipe_ingredients (menu_id, ingredient_id, quantity)
                VALUES (:menu_id, :ingredient_id, :quantity)
            """)
            for item in payload.recipe:
                db.execute(insert_recipe_query, {
                    "menu_id": new_menu_id,
                    "ingredient_id": item.ingredient_id,
                    "quantity": item.quantity
                })

        db.commit()
        return {"status": "success", "message": "Menu berhasil dirilis!"}
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Create menu error - {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/{menu_id}")
def update_menu(menu_id: str, payload: UpdateMenuRequest, db: Session = Depends(get_db)):
    try:
        # Persiapkan data yang akan diupdate (hanya field yang tidak None)
        update_data = {k: v for k, v in payload.dict().items() if v is not None and k != "recipe"}
        
        if update_data:
            set_clause = ", ".join([f"{key} = :{key}" for key in update_data.keys()])
            update_query = text(f"""
                UPDATE menus
                SET {set_clause}
                WHERE id = :id
            """)
            update_data["id"] = menu_id
            db.execute(update_query, update_data)
        
        # Jika recipe diupdate
        if payload.recipe is not None:
            # Hapus resep lama terlebih dahulu
            delete_recipe_query = text("DELETE FROM recipe_ingredients WHERE menu_id = :menu_id")
            db.execute(delete_recipe_query, {"menu_id": menu_id})
            
            # Simpan resep baru
            if payload.recipe:
                insert_recipe_query = text("""
                    INSERT INTO recipe_ingredients (menu_id, ingredient_id, quantity)
                    VALUES (:menu_id, :ingredient_id, :quantity)
                """)
                for item in payload.recipe:
                    db.execute(insert_recipe_query, {
                        "menu_id": menu_id,
                        "ingredient_id": item.ingredient_id,
                        "quantity": item.quantity
                    })
        
        db.commit()
        return {"status": "success", "message": "Menu berhasil diperbarui!"}
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Update menu error - {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{menu_id}")
def delete_menu(menu_id: str, db: Session = Depends(get_db)):
    try:
        # Menghapus resep otomatis akan terjadi berkat ON DELETE CASCADE di database
        delete_query = text("DELETE FROM menus WHERE id = :id")
        result = db.execute(delete_query, {"id": menu_id})
        db.commit()
        
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Menu tidak ditemukan")
        
        return {"status": "success", "message": "Menu dihapus"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Delete menu error - {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))