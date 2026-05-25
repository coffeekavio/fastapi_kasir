from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List
from database import get_db

router = APIRouter(prefix="/api/customers", tags=["Pelanggan & Promo"])

# ==========================================
# SKEMA PYDANTIC (VALIDASI DATA)
# ==========================================
class LoyaltySettingUpdate(BaseModel):
    cafe_id: str
    earn_amount_per_point: float
    reward_type: str = Field(..., description="'rupiah' atau 'percentage'")
    reward_value: float

class CustomerCreate(BaseModel):
    cafe_id: str
    name: str = Field(..., min_length=2)
    phone: str = Field(..., min_length=9)
    points: float = 0

class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    points: Optional[float] = None


# ==========================================
# 1. ENDPOINT: PENGATURAN POIN (SETTINGS)
# ==========================================

@router.get("/settings", summary="Ambil pengaturan loyalitas kafe")
def get_loyalty_settings(cafe_id: str, db: Session = Depends(get_db)):
    try:
        query = text("""
            SELECT id, cafe_id, earn_amount_per_point, reward_type, reward_value, created_at
            FROM loyalty_settings
            WHERE cafe_id = :cafe_id
        """)
        result = db.execute(query, {"cafe_id": cafe_id}).mappings().fetchone()
        
        if not result:
            return {"status": "success", "data": None, "message": "Belum ada pengaturan"}
        return {"status": "success", "data": dict(result)}
    except Exception as e:
        print(f"DEBUG: Get loyalty settings error - {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/settings", summary="Simpan/Update pengaturan loyalitas")
def upsert_loyalty_settings(payload: LoyaltySettingUpdate, db: Session = Depends(get_db)):
    try:
        # Cek apakah cabang ini sudah punya pengaturan
        check_query = text("SELECT id FROM loyalty_settings WHERE cafe_id = :cafe_id")
        existing = db.execute(check_query, {"cafe_id": payload.cafe_id}).fetchone()
        
        if existing:
            # UPDATE datanya
            update_query = text("""
                UPDATE loyalty_settings
                SET earn_amount_per_point = :earn_amount_per_point,
                    reward_type = :reward_type,
                    reward_value = :reward_value
                WHERE cafe_id = :cafe_id
                RETURNING id, cafe_id, earn_amount_per_point, reward_type, reward_value, created_at
            """)
            result = db.execute(update_query, {
                "cafe_id": payload.cafe_id,
                "earn_amount_per_point": payload.earn_amount_per_point,
                "reward_type": payload.reward_type,
                "reward_value": payload.reward_value
            }).mappings().fetchone()
        else:
            # INSERT data baru
            insert_query = text("""
                INSERT INTO loyalty_settings (cafe_id, earn_amount_per_point, reward_type, reward_value, created_at)
                VALUES (:cafe_id, :earn_amount_per_point, :reward_type, :reward_value, NOW())
                RETURNING id, cafe_id, earn_amount_per_point, reward_type, reward_value, created_at
            """)
            result = db.execute(insert_query, {
                "cafe_id": payload.cafe_id,
                "earn_amount_per_point": payload.earn_amount_per_point,
                "reward_type": payload.reward_type,
                "reward_value": payload.reward_value
            }).mappings().fetchone()
            
        db.commit()
        return {"status": "success", "message": "Pengaturan Poin berhasil disimpan!", "data": dict(result) if result else None}
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Upsert loyalty settings error - {str(e)}")
        raise HTTPException(status_code=400, detail=f"Gagal menyimpan pengaturan: {str(e)}")


# ==========================================
# 2. ENDPOINT: CRUD DATA PELANGGAN (MEMBER)
# ==========================================

@router.get("/", summary="Ambil daftar pelanggan / cari berdasarkan nomor HP")
def get_customers(cafe_id: str, phone: Optional[str] = None, db: Session = Depends(get_db)):
    try:
        if phone:
            # Fitur pencarian otomatis di kasir (berdasarkan nomor HP)
            query = text("""
                SELECT id, cafe_id, name, phone, points, created_at
                FROM customers
                WHERE cafe_id = :cafe_id AND phone ILIKE :phone
                ORDER BY created_at DESC
            """)
            results = db.execute(query, {"cafe_id": cafe_id, "phone": f"%{phone}%"}).mappings().fetchall()
        else:
            # Ambil semua pelanggan di kafe ini
            query = text("""
                SELECT id, cafe_id, name, phone, points, created_at
                FROM customers
                WHERE cafe_id = :cafe_id
                ORDER BY created_at DESC
            """)
            results = db.execute(query, {"cafe_id": cafe_id}).mappings().fetchall()
        
        return {"status": "success", "data": [dict(row) for row in results]}
    except Exception as e:
        print(f"DEBUG: Get customers error - {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/", summary="Daftarkan pelanggan baru")
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
    try:
        # Validasi: Cek apakah nomor HP sudah terdaftar di cabang yang sama
        check_query = text("""
            SELECT id FROM customers
            WHERE cafe_id = :cafe_id AND phone = :phone
        """)
        existing = db.execute(check_query, {"cafe_id": payload.cafe_id, "phone": payload.phone}).fetchone()
        
        if existing:
            raise HTTPException(status_code=400, detail="Nomor Handphone ini sudah terdaftar sebagai member!")
            
        # Insert pelanggan baru
        insert_query = text("""
            INSERT INTO customers (cafe_id, name, phone, points, created_at)
            VALUES (:cafe_id, :name, :phone, :points, NOW())
            RETURNING id, cafe_id, name, phone, points, created_at
        """)
        
        result = db.execute(insert_query, {
            "cafe_id": payload.cafe_id,
            "name": payload.name,
            "phone": payload.phone,
            "points": payload.points
        }).mappings().fetchone()
        
        db.commit()
        return {"status": "success", "message": "Member baru berhasil didaftarkan!", "data": dict(result) if result else None}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Create customer error - {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{customer_id}", summary="Update data pelanggan (Edit nama/HP/Poin)")
def update_customer(customer_id: str, payload: CustomerUpdate, db: Session = Depends(get_db)):
    try:
        # Hapus field yang bernilai None dari payload
        update_data = {k: v for k, v in payload.dict().items() if v is not None}
        
        if not update_data:
            raise HTTPException(status_code=400, detail="Tidak ada data yang diubah")
        
        # Build dynamic update query
        set_clause = ", ".join([f"{key} = :{key}" for key in update_data.keys()])
        update_query = text(f"""
            UPDATE customers
            SET {set_clause}
            WHERE id = :id
            RETURNING id, cafe_id, name, phone, points, created_at
        """)
        
        update_data["id"] = customer_id
        result = db.execute(update_query, update_data).mappings().fetchone()
        db.commit()
        
        if not result:
            raise HTTPException(status_code=404, detail="Pelanggan tidak ditemukan")
            
        return {"status": "success", "message": "Data member berhasil diupdate", "data": dict(result)}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Update customer error - {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{customer_id}", summary="Hapus data pelanggan")
def delete_customer(customer_id: str, db: Session = Depends(get_db)):
    try:
        # Berkat ON DELETE CASCADE di database, ini aman dilakukan
        delete_query = text("DELETE FROM customers WHERE id = :id")
        result = db.execute(delete_query, {"id": customer_id})
        db.commit()
        
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Pelanggan tidak ditemukan")
             
        return {"status": "success", "message": "Data member berhasil dihapus"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Delete customer error - {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))