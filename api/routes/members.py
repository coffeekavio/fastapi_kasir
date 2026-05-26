from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List
from datetime import datetime
from database import get_db
import json

router = APIRouter()

# ============ PYDANTIC MODELS ============

class MemberCreate(BaseModel):
    cafe_id: str = Field(..., description="ID kafe tempat member terdaftar")
    name: str = Field(..., min_length=2, description="Nama lengkap member")
    phone: Optional[str] = Field(None, description="Nomor telepon member")
    points: int = Field(default=0, ge=0, description="Poin awal member")

class MemberUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, description="Nama member")
    phone: Optional[str] = Field(None, description="Nomor telepon")
    points: Optional[int] = Field(None, ge=0, description="Poin member")

class MemberResponse(BaseModel):
    id: str
    cafe_id: str
    name: str
    phone: Optional[str]
    points: int
    created_at: datetime

# ============ ENDPOINTS ============

# 1. GET: Ambil daftar member berdasarkan cafe_id
@router.get("/api/members/", summary="Ambil daftar member berdasarkan cafe_id")
def get_members(cafe_id: str, db: Session = Depends(get_db)):
    """
    Mengambil semua member yang terdaftar di kafe tertentu.
    """
    try:
        query = text("""
            SELECT id, cafe_id, name, phone, points, created_at
            FROM members
            WHERE cafe_id = :cafe_id
            ORDER BY created_at DESC
        """)
        
        results = db.execute(query, {"cafe_id": cafe_id}).mappings().fetchall()
        
        return {
            "status": "success",
            "data": [dict(row) for row in results]
        }
    except Exception as e:
        print(f"DEBUG: Get members error - {str(e)}")
        raise HTTPException(status_code=500, detail=f"Gagal mengambil data member: {str(e)}")


# 2. GET: Ambil detail member berdasarkan member_id
@router.get("/api/members/{member_id}", summary="Ambil detail member berdasarkan ID")
def get_member(member_id: str, db: Session = Depends(get_db)):
    """
    Mengambil detail member berdasarkan ID member.
    """
    try:
        query = text("""
            SELECT id, cafe_id, name, phone, points, created_at
            FROM members
            WHERE id = :id
        """)
        
        result = db.execute(query, {"id": member_id}).mappings().fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Member tidak ditemukan")
        
        return {
            "status": "success",
            "data": dict(result)
        }
    except HTTPException as http_e:
        raise http_e
    except Exception as e:
        print(f"DEBUG: Get member error - {str(e)}")
        raise HTTPException(status_code=500, detail=f"Gagal mengambil data member: {str(e)}")


# 3. POST: Tambah member baru
@router.post("/api/create-members", summary="Tambah member baru", status_code=status.HTTP_201_CREATED)
def create_member(payload: MemberCreate, db: Session = Depends(get_db)):
    """
    Membuat member baru di kafe tertentu.
    """
    try:
        # Cek apakah cafe_id valid
        cafe_check = text("SELECT name FROM cafes WHERE id = :cafe_id")
        cafe_result = db.execute(cafe_check, {"cafe_id": payload.cafe_id}).fetchone()
        
        if not cafe_result:
            raise HTTPException(status_code=400, detail="Cafe ID tidak valid")
        
        cafe_name = cafe_result.name
        
        # Insert member baru dengan ID otomatis
        insert_query = text("""
            INSERT INTO members (id, cafe_id, name, phone, points, created_at)
            VALUES (gen_random_uuid(), :cafe_id, :name, :phone, :points, NOW())
            RETURNING id, cafe_id, name, phone, points, created_at
        """)
        
        result = db.execute(insert_query, {
            "cafe_id": payload.cafe_id,
            "name": payload.name,
            "phone": payload.phone,
            "points": payload.points
        }).fetchone()
        
        db.commit()
        
        if not result:
            raise HTTPException(status_code=400, detail="Gagal membuat member baru")
        
        return {
            "status": "success",
            "message": f"Member '{payload.name}' berhasil ditambahkan ke kafe {cafe_name}",
            "data": dict(result._mapping) if result else None,
            "metadata": {
                "member_id": result.id,
                "cafe_name": cafe_name,
                "total_points": result.points,
                "registration_date": result.created_at
            }
        }
    except HTTPException as http_e:
        db.rollback()
        raise http_e
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Create member error - {str(e)}")
        raise HTTPException(status_code=400, detail=f"Gagal membuat member: {str(e)}")


# 4. PUT: Update data member (nama, telepon, poin)
@router.put("/api/update-members/{member_id}", summary="Update data member")
def update_member(member_id: str, payload: MemberUpdate, db: Session = Depends(get_db)):
    """
    Memperbarui data member (nama, telepon, atau poin).
    """
    try:
        # Ambil data member sebelumnya
        check_query = text("SELECT id, name, phone, points FROM members WHERE id = :id")
        member_old = db.execute(check_query, {"id": member_id}).fetchone()
        
        if not member_old:
            raise HTTPException(status_code=404, detail="Member tidak ditemukan")
        
        old_data = dict(member_old._mapping) if member_old else {}
        
        # Build update query dinamis berdasarkan field yang diisi
        update_data = {}
        changes = []
        
        if payload.name and payload.name != member_old.name:
            update_data["name"] = payload.name
            changes.append(f"nama ({member_old.name} → {payload.name})")
        if payload.phone is not None and payload.phone != member_old.phone:
            update_data["phone"] = payload.phone
            changes.append(f"telepon ({member_old.phone} → {payload.phone})")
        if payload.points is not None and payload.points != member_old.points:
            update_data["points"] = payload.points
            changes.append(f"poin ({member_old.points} → {payload.points})")
        
        if not update_data:
            raise HTTPException(status_code=400, detail="Tidak ada data yang berubah")
        
        # Build SQL update statement
        set_clause = ", ".join([f"{key} = :{key}" for key in update_data.keys()])
        update_query = text(f"""
            UPDATE members
            SET {set_clause}
            WHERE id = :id
            RETURNING id, cafe_id, name, phone, points, created_at
        """)
        
        update_data["id"] = member_id
        result = db.execute(update_query, update_data).fetchone()
        db.commit()
        
        if not result:
            raise HTTPException(status_code=400, detail="Gagal memperbarui member")
        
        return {
            "status": "success",
            "message": f"Data member berhasil diperbarui: {', '.join(changes)}",
            "data": dict(result._mapping) if result else None,
            "metadata": {
                "member_id": member_id,
                "fields_updated": len(changes),
                "changes": changes,
                "previous_data": old_data,
                "updated_at": result.created_at
            }
        }
    except HTTPException as http_e:
        db.rollback()
        raise http_e
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Update member error - {str(e)}")
        raise HTTPException(status_code=400, detail=f"Gagal memperbarui member: {str(e)}")


# 5. PUT: Update poin member (tambah atau kurangi)
@router.put("/api/members/{member_id}/points", summary="Update poin member")
def update_member_points(member_id: str, points_change: int, db: Session = Depends(get_db)):
    """
    Memperbarui poin member (tambah atau kurangi).
    Parameter: points_change (bisa positif atau negatif)
    """
    try:
        # Get current points
        get_query = text("SELECT points FROM members WHERE id = :id")
        result = db.execute(get_query, {"id": member_id}).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Member tidak ditemukan")
        
        new_points = result.points + points_change
        
        if new_points < 0:
            raise HTTPException(status_code=400, detail="Poin tidak boleh negatif")
        
        # Update points
        update_query = text("""
            UPDATE members
            SET points = :new_points
            WHERE id = :id
            RETURNING id, cafe_id, name, phone, points, created_at
        """)
        
        updated = db.execute(update_query, {
            "id": member_id,
            "new_points": new_points
        }).fetchone()
        
        db.commit()
        
        return {
            "status": "success",
            "message": f"Poin member berhasil diperbarui",
            "data": dict(updated._mapping) if updated else None
        }
    except HTTPException as http_e:
        db.rollback()
        raise http_e
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Update member points error - {str(e)}")
        raise HTTPException(status_code=400, detail=f"Gagal memperbarui poin: {str(e)}")


# 6. DELETE: Hapus member
@router.delete("/api/delete-members/{member_id}", summary="Hapus member dari sistem")
def delete_member(member_id: str, db: Session = Depends(get_db)):
    """
    Menghapus member dari sistem.
    """
    try:
        # Ambil data member sebelum dihapus untuk audit trail
        get_query = text("SELECT id, name, email, phone, points, created_at FROM members WHERE id = :id")
        member_data = db.execute(get_query, {"id": member_id}).fetchone()
        
        if not member_data:
            raise HTTPException(status_code=404, detail="Member tidak ditemukan")
        
        deleted_data = dict(member_data._mapping) if member_data else {}
        member_name = member_data.name
        
        # Hapus member
        delete_query = text("DELETE FROM members WHERE id = :id")
        result = db.execute(delete_query, {"id": member_id})
        db.commit()
        
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Member tidak ditemukan")
        
        return {
            "status": "success",
            "message": f"Member '{member_name}' berhasil dihapus dari sistem",
            "metadata": {
                "member_id": member_id,
                "deleted_member_name": member_name,
                "deleted_at": datetime.now().isoformat(),
                "deleted_data": deleted_data,
                "note": "Data member yang dihapus disimpan untuk audit trail"
            }
        }
    except HTTPException as http_e:
        db.rollback()
        raise http_e
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Delete member error - {str(e)}")
        raise HTTPException(status_code=400, detail=f"Gagal menghapus member: {str(e)}")
