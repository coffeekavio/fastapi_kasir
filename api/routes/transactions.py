import uuid
from datetime import datetime
import random
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional

from database import get_db
from ..websockets import manager # Untuk update layar kasir otomatis

router = APIRouter(prefix="/api/transactions", tags=["Transaksi"])

# ==========================================
# 1. PYDANTIC SCHEMAS (Menerima Data dari Flutter)
# ==========================================
class TransactionItemCreate(BaseModel):
    menu_id: Optional[str] = None
    quantity: int = Field(..., gt=0)
    is_manual: bool = False
    manual_item_name: Optional[str] = None
    base_price: int = 0
    price: int = Field(..., ge=0)
    item_discount: int = 0
    override_reason: Optional[str] = None
    note: Optional[str] = None

class TransactionCreate(BaseModel):
    cafe_id: str
    cashier_id: str
    member_id: Optional[str] = None
    voucher_id: Optional[str] = None
    # Update deskripsi menjadi cash atau qris_static
    payment_method: str = Field(..., description="'cash' atau 'qris_static'")
    amount_tendered: int
    discount_amount: int = 0
    voucher_discount_amount: int = 0
    items: List[TransactionItemCreate]

class TransactionUpdate(BaseModel):
    discount_amount: Optional[int] = None
    voucher_discount_amount: Optional[int] = None
    payment_method: Optional[str] = None
    amount_tendered: Optional[int] = None
    status: Optional[str] = None

# ==========================================
# 2. ENDPOINT: CHECKOUT (OPSI A: LANGSUNG LUNAS)
# ==========================================
@router.post("/checkout", summary="Proses Checkout (Langsung Lunas)")
async def checkout(payload: TransactionCreate, db: Session = Depends(get_db)):
    try:
        # Hitung Subtotal
        calculated_subtotal = sum(((item.quantity * item.price) - item.item_discount) for item in payload.items)
        total_amount = max(0, calculated_subtotal - payload.discount_amount - payload.voucher_discount_amount)
        
        transaction_id = str(uuid.uuid4())
        date_str = datetime.now().strftime("%Y%m%d")
        receipt_number = f"TRX-{date_str}-{random.randint(1000, 9999)}"

        # OPSI A: Apapun metode pembayarannya, langsung diset 'completed' (LUNAS)
        initial_status = "completed"
        
        # Kembalian hanya dihitung jika bayar tunai (cash)
        change_amount = payload.amount_tendered - total_amount if payload.payment_method.lower() == "cash" else 0

        # Simpan ke tabel transactions
        insert_trx_query = text("""
            INSERT INTO transactions 
            (id, cafe_id, cashier_id, member_id, voucher_id, receipt_number, 
             subtotal, discount_amount, voucher_discount_amount, total_amount, 
             payment_method, amount_tendered, change_amount, status)
            VALUES 
            (:id, :cafe_id, :cashier_id, :member_id, :voucher_id, :receipt_number,
             :subtotal, :discount_amount, :voucher_discount_amount, :total_amount,
             :payment_method, :amount_tendered, :change_amount, :status)
        """)
        db.execute(insert_trx_query, {
            "id": transaction_id, "cafe_id": payload.cafe_id, "cashier_id": payload.cashier_id,
            "member_id": payload.member_id, "voucher_id": payload.voucher_id, "receipt_number": receipt_number,
            "subtotal": calculated_subtotal, "discount_amount": payload.discount_amount,
            "voucher_discount_amount": payload.voucher_discount_amount, "total_amount": total_amount,
            "payment_method": payload.payment_method, "amount_tendered": payload.amount_tendered,
            "change_amount": change_amount, "status": initial_status
        })

        # Simpan ke tabel transaction_items
        for item in payload.items:
            item_subtotal = (item.quantity * item.price) - item.item_discount
            insert_item_query = text("""
                INSERT INTO transaction_items 
                (transaction_id, menu_id, quantity, is_manual, manual_item_name, 
                 base_price, price, item_discount, override_reason, subtotal, note)
                VALUES 
                (:transaction_id, :menu_id, :quantity, :is_manual, :manual_item_name,
                 :base_price, :price, :item_discount, :override_reason, :subtotal, :note)
            """)
            db.execute(insert_item_query, {
                "transaction_id": transaction_id, "menu_id": item.menu_id, "quantity": item.quantity,
                "is_manual": item.is_manual, "manual_item_name": item.manual_item_name,
                "base_price": item.base_price, "price": item.price, "item_discount": item.item_discount,
                "override_reason": item.override_reason, "subtotal": item_subtotal, "note": item.note
            })

        db.commit()

        # Beri sinyal WebSocket untuk me-refresh data transaksi di layar
        await manager.broadcast("REFRESH_TRANSAKSI")
        
        return {
            "status": "success",
            "message": "Transaksi berhasil disimpan dan Lunas",
            "data": {"transaction_id": transaction_id, "receipt_number": receipt_number}
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Gagal memproses transaksi: {str(e)}")

# ==========================================
# 3. ENDPOINT: GET RIWAYAT TRANSAKSI (SEMUA)
# ==========================================
@router.get("/", summary="Ambil Daftar Riwayat Transaksi")
async def get_all_transactions(cafe_id: Optional[str] = None, db: Session = Depends(get_db)):
    try:
        # Query dasar (mengambil dari tabel transactions)
        query_str = """
            SELECT id, receipt_number, total_amount, payment_method, status, created_at 
            FROM transactions 
        """
        params = {}
        
        # Opsional: Jika ingin memfilter berdasarkan kafe tertentu (Multi-tenant)
        if cafe_id:
            query_str += " WHERE cafe_id = :cafe_id "
            params["cafe_id"] = cafe_id
            
        # Urutkan dari yang paling baru. 
        # paling baru. 
        query_str += " ORDER BY created_at DESC, receipt_number DESC" 
        
        result = db.execute(text(query_str), params).mappings().all()
        
        return {
            "status": "success",
            "message": "Berhasil mengambil riwayat transaksi",
            "data": [dict(row) for row in result]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal mengambil riwayat transaksi: {str(e)}")


# ==========================================
# 4. ENDPOINT: GET DETAIL TRANSAKSI (BESERTA ITEM)
# ==========================================
@router.get("/{transaction_id}", summary="Ambil Detail Transaksi Lengkap")
async def get_transaction_detail(transaction_id: str, db: Session = Depends(get_db)):
    try:
        # 1. Ambil data induk transaksi
        trx_query = text("SELECT * FROM transactions WHERE id = :id")
        trx = db.execute(trx_query, {"id": transaction_id}).mappings().first()
        
        if not trx:
            raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
            
        # 2. Ambil data item dengan join ke menu table untuk mendapat nama menu
        items_query = text("""
            SELECT ti.*, m.name as menu_name
            FROM transaction_items ti
            LEFT JOIN menus m ON ti.menu_id = m.id
            WHERE ti.transaction_id = :id
        """)
        items = db.execute(items_query, {"id": transaction_id}).mappings().all()
        
        # 3. Gabungkan data
        trx_data = dict(trx)
        trx_data["items"] = [dict(item) for item in items]
        
        return {
            "status": "success",
            "message": "Berhasil mengambil detail transaksi",
            "data": trx_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal mengambil detail transaksi: {str(e)}")
       
# ==========================================
# 5. DELETE
# ==========================================
@router.delete("/{transaction_id}", summary="Hapus Transaksi")
async def delete_transaction(transaction_id: str, db: Session = Depends(get_db)):
    try:
        delete_query = text("DELETE FROM transactions WHERE id = :id")
        db.execute(delete_query, {"id": transaction_id})
        db.commit()
        return {"status": "success", "message": "Transaksi berhasil dihapus"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Gagal menghapus transaksi: {str(e)}")
    
# ==========================================
# 6. ENDPOINT: UPDATE/EDIT TRANSAKSI
# ==========================================
@router.patch("/{transaction_id}", summary="Update/Edit Transaksi")
async def update_transaction(
    transaction_id: str, 
    payload: TransactionUpdate, 
    db: Session = Depends(get_db)
):
    try:
        # 1. Cek apakah transaksi ada
        trx_query = text("SELECT * FROM transactions WHERE id = :id")
        trx = db.execute(trx_query, {"id": transaction_id}).mappings().first()
        
        if not trx:
            raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
        
        # 2. Convert ke dict untuk update
        trx_data = dict(trx)
        
        # 3. Hitung ulang total jika ada perubahan discount atau voucher
        update_fields = {}
        
        if payload.discount_amount is not None:
            update_fields["discount_amount"] = payload.discount_amount
        
        if payload.voucher_discount_amount is not None:
            update_fields["voucher_discount_amount"] = payload.voucher_discount_amount
        
        if payload.payment_method is not None:
            update_fields["payment_method"] = payload.payment_method
        
        if payload.amount_tendered is not None:
            update_fields["amount_tendered"] = payload.amount_tendered
        
        if payload.status is not None:
            update_fields["status"] = payload.status
        
        # 4. Hitung total_amount baru jika ada perubahan discount
        if "discount_amount" in update_fields or "voucher_discount_amount" in update_fields:
            discount_amount = update_fields.get("discount_amount", trx_data["discount_amount"])
            voucher_discount_amount = update_fields.get("voucher_discount_amount", trx_data["voucher_discount_amount"])
            subtotal = trx_data["subtotal"]
            new_total = max(0, subtotal - discount_amount - voucher_discount_amount)
            update_fields["total_amount"] = new_total
            
            # Update change amount jika payment method cash
            payment_method = update_fields.get("payment_method", trx_data["payment_method"])
            amount_tendered = update_fields.get("amount_tendered", trx_data["amount_tendered"])
            
            if payment_method.lower() == "cash":
                update_fields["change_amount"] = max(0, amount_tendered - new_total)
            else:
                update_fields["change_amount"] = 0
        elif "amount_tendered" in update_fields or "payment_method" in update_fields:
            # Hanya update change jika payment method atau amount_tendered berubah
            payment_method = update_fields.get("payment_method", trx_data["payment_method"])
            amount_tendered = update_fields.get("amount_tendered", trx_data["amount_tendered"])
            
            if payment_method.lower() == "cash":
                update_fields["change_amount"] = max(0, amount_tendered - trx_data["total_amount"])
            else:
                update_fields["change_amount"] = 0
        
        # 5. Build UPDATE query
        if update_fields:
            set_clause = ", ".join([f"{key} = :{key}" for key in update_fields.keys()])
            update_query = text(f"UPDATE transactions SET {set_clause} WHERE id = :id")
            update_fields["id"] = transaction_id
            db.execute(update_query, update_fields)
            db.commit()
        
        # 6. Ambil data transaksi yang sudah diupdate
        updated_trx = db.execute(trx_query, {"id": transaction_id}).mappings().first()
        
        # Beri sinyal WebSocket untuk me-refresh data transaksi di layar
        await manager.broadcast("REFRESH_TRANSAKSI")
        
        return {
            "status": "success",
            "message": "Transaksi berhasil diupdate",
            "data": dict(updated_trx)
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Gagal mengupdate transaksi: {str(e)}")