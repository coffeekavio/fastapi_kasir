from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from datetime import datetime
from database import get_db

router = APIRouter()

# ============ PYDANTIC MODELS ============

class VoucherCreate(BaseModel):
    cafe_id: str = Field(..., description="ID kafe pemilik voucher")
    name: str = Field(..., description="Nama Promo (Misal: Promo Kemerdekaan)")
    discount_percentage: int = Field(..., ge=1, le=100, description="Diskon dalam persen")
    min_purchase: int = Field(default=0, ge=0, description="Minimal belanja")
    start_date: datetime = Field(..., description="Tanggal mulai berlaku")
    end_date: datetime = Field(..., description="Tanggal berakhir promo")
    is_active: bool = Field(default=True, description="Status aktif voucher")

class VoucherUpdate(BaseModel):
    name: Optional[str] = None
    discount_percentage: Optional[int] = Field(None, ge=1, le=100)
    min_purchase: Optional[int] = Field(None, ge=0)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_active: Optional[bool] = None

# ============ ENDPOINTS ============

# 1. POST: Buat Voucher Baru (Untuk Manajer)
@router.post("/api/vouchers", summary="Buat promo/voucher baru")
def create_voucher(payload: VoucherCreate, db: Session = Depends(get_db)):
    try:
        # Validasi tanggal
        if payload.end_date <= payload.start_date:
            raise HTTPException(status_code=400, detail="Tanggal berakhir harus lebih besar dari tanggal mulai")

        insert_query = text("""
            INSERT INTO vouchers (cafe_id, name, discount_percentage, min_purchase, start_date, end_date, is_active)
            VALUES (:cafe_id, :name, :discount_percentage, :min_purchase, :start_date, :end_date, :is_active)
            RETURNING id, cafe_id, name, discount_percentage, min_purchase, start_date, end_date, is_active, created_at
        """)
        
        result = db.execute(insert_query, {
            "cafe_id": payload.cafe_id,
            "name": payload.name,
            "discount_percentage": payload.discount_percentage,
            "min_purchase": payload.min_purchase,
            "start_date": payload.start_date,
            "end_date": payload.end_date,
            "is_active": payload.is_active
        }).fetchone()
        
        db.commit()
        
        return {
            "status": "success",
            "message": "Voucher berhasil dibuat",
            "data": dict(result._mapping) if result else None
        }
    except HTTPException as http_e:
        db.rollback()
        raise http_e
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Gagal membuat voucher: {str(e)}")

# 2. GET: Ambil SEMUA Voucher Kafe (Untuk Dashboard Manajer)
@router.get("/api/vouchers/all/{cafe_id}", summary="Ambil semua riwayat voucher")
def get_all_vouchers(cafe_id: str, db: Session = Depends(get_db)):
    try:
        query = text("""
            SELECT id, name, discount_percentage, min_purchase, start_date, end_date, is_active 
            FROM vouchers 
            WHERE cafe_id = :cafe_id 
            ORDER BY created_at DESC
        """)
        results = db.execute(query, {"cafe_id": cafe_id}).mappings().fetchall()
        
        return {"status": "success", "data": [dict(row) for row in results]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal mengambil data: {str(e)}")

# 3. GET: Ambil HANYA Voucher yang sedang AKTIF & BERLAKU HARI INI (Untuk Kasir Flutter)
@router.get("/api/vouchers/active/{cafe_id}", summary="Ambil voucher yang siap dipakai hari ini")
def get_active_vouchers(cafe_id: str, db: Session = Depends(get_db)):
    """
    Endpoint ini sangat penting untuk layar kasir. 
    Hanya mengembalikan voucher yang is_active = TRUE dan tanggal hari ini berada di antara start_date dan end_date.
    """
    try:
        query = text("""
            SELECT id, name, discount_percentage, min_purchase 
            FROM vouchers 
            WHERE cafe_id = :cafe_id 
              AND is_active = TRUE 
              AND NOW() BETWEEN start_date AND end_date
            ORDER BY discount_percentage DESC
        """)
        results = db.execute(query, {"cafe_id": cafe_id}).mappings().fetchall()
        
        return {"status": "success", "data": [dict(row) for row in results]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal mengambil data voucher aktif: {str(e)}")

# 4. PUT: Update Voucher (Edit atau Matikan Promo)
@router.put("/api/vouchers/{voucher_id}", summary="Update data voucher")
def update_voucher(voucher_id: str, payload: VoucherUpdate, db: Session = Depends(get_db)):
    try:
        update_data = {k: v for k, v in payload.dict(exclude_none=True).items()}
        if not update_data:
            raise HTTPException(status_code=400, detail="Tidak ada data yang diubah")

        set_clause = ", ".join([f"{key} = :{key}" for key in update_data.keys()])
        query = text(f"""
            UPDATE vouchers SET {set_clause} 
            WHERE id = :id 
            RETURNING id, name, is_active
        """)
        
        update_data["id"] = voucher_id
        result = db.execute(query, update_data).fetchone()
        db.commit()

        if not result:
            raise HTTPException(status_code=404, detail="Voucher tidak ditemukan")

        return {"status": "success", "message": "Voucher berhasil diperbarui", "data": dict(result._mapping)}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Gagal update: {str(e)}")

# 5. DELETE: Hapus Voucher
@router.delete("/api/vouchers/{voucher_id}", summary="Hapus voucher")
def delete_voucher(voucher_id: str, db: Session = Depends(get_db)):
    try:
        result = db.execute(text("DELETE FROM vouchers WHERE id = :id"), {"id": voucher_id})
        db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Voucher tidak ditemukan")
        return {"status": "success", "message": "Voucher berhasil dihapus"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Gagal hapus: {str(e)}")