from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from database import get_db

router = APIRouter(
    prefix="/api/kategori",
    tags=["Kategori"],
    responses={404: {"description": "Not found"}},
)


# Pydantic Models
class KategoriCreate(BaseModel):
    cafe_id: str = Field(..., description="ID kafe")
    name: str = Field(..., min_length=1, max_length=100)


class KategoriUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)


class KategoriResponse(BaseModel):
    id: str
    cafe_id: str
    name: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# GET all categories by cafe_id
@router.get("/", response_model=List[KategoriResponse])
async def get_all_categories(cafe_id: str, db: Session = Depends(get_db)):
    try:
        query = text("""
            SELECT id, cafe_id, name, created_at
            FROM categories
            WHERE cafe_id = :cafe_id
            ORDER BY created_at DESC
        """)
        
        results = db.execute(query, {"cafe_id": cafe_id}).mappings().fetchall()
        return [dict(row) for row in results]
    except Exception as e:
        print(f"DEBUG: Get categories error - {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch categories: {str(e)}"
        )


# GET category by id
@router.get("/{kategori_id}", response_model=KategoriResponse)
async def get_category(kategori_id: str, cafe_id: str, db: Session = Depends(get_db)):
    try:
        query = text("""
            SELECT id, cafe_id, name, created_at
            FROM categories
            WHERE id = :id AND cafe_id = :cafe_id
        """)
        
        result = db.execute(query, {"id": kategori_id, "cafe_id": cafe_id}).mappings().fetchone()
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Kategori tidak ditemukan"
            )
        return dict(result)
    except HTTPException:
        raise
    except Exception as e:
        print(f"DEBUG: Get category error - {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch kategori: {str(e)}"
        )


# POST create new category
@router.post("/", response_model=KategoriResponse, status_code=status.HTTP_201_CREATED)
async def create_category(kategori: KategoriCreate, db: Session = Depends(get_db)):
    try:
        # Verify cafe exists
        cafe_check = text("SELECT id FROM cafes WHERE id = :cafe_id")
        cafe_result = db.execute(cafe_check, {"cafe_id": kategori.cafe_id}).fetchone()
        
        if not cafe_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cafe tidak ditemukan"
            )
        
        # Insert new category
        insert_query = text("""
            INSERT INTO categories (cafe_id, name, created_at)
            VALUES (:cafe_id, :name, NOW())
            RETURNING id, cafe_id, name, created_at
        """)
        
        result = db.execute(insert_query, {
            "cafe_id": kategori.cafe_id,
            "name": kategori.name
        }).mappings().fetchone()
        
        db.commit()
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Gagal membuat kategori"
            )
        
        return dict(result)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Create category error - {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create kategori: {str(e)}"
        )


# PUT update category
@router.put("/{kategori_id}", response_model=KategoriResponse)
async def update_category(kategori_id: str, cafe_id: str, kategori: KategoriUpdate, db: Session = Depends(get_db)):
    try:
        # Verify kategori exists and belongs to cafe
        existing = text("""
            SELECT id FROM categories
            WHERE id = :id AND cafe_id = :cafe_id
        """)
        existing_result = db.execute(existing, {"id": kategori_id, "cafe_id": cafe_id}).fetchone()
        
        if not existing_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Kategori tidak ditemukan"
            )
        
        if not kategori.name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nama kategori tidak boleh kosong"
            )
        
        # Update category
        update_query = text("""
            UPDATE categories
            SET name = :name
            WHERE id = :id
            RETURNING id, cafe_id, name, created_at
        """)
        
        result = db.execute(update_query, {
            "id": kategori_id,
            "name": kategori.name
        }).mappings().fetchone()
        
        db.commit()
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Gagal memperbarui kategori"
            )
        
        return dict(result)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Update category error - {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update kategori: {str(e)}"
        )


# DELETE category
@router.delete("/{kategori_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(kategori_id: str, cafe_id: str, db: Session = Depends(get_db)):
    try:
        # Verify kategori exists and belongs to cafe
        existing = text("""
            SELECT id FROM categories
            WHERE id = :id AND cafe_id = :cafe_id
        """)
        existing_result = db.execute(existing, {"id": kategori_id, "cafe_id": cafe_id}).fetchone()
        
        if not existing_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Kategori tidak ditemukan"
            )
        
        # Delete category
        delete_query = text("DELETE FROM categories WHERE id = :id")
        db.execute(delete_query, {"id": kategori_id})
        db.commit()
        
        return None
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Delete category error - {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete kategori: {str(e)}"
        )
