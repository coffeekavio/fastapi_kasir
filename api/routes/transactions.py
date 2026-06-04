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
# (BLOK XENDIT WEBHOOK DIHAPUS KARENA MENGGUNAKAN OPSI A)
# ==========================================