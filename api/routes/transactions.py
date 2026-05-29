import httpx
import base64
import uuid
from datetime import datetime
import random
from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional

from database import get_db
from ..websockets import manager # Untuk update layar kasir otomatis

router = APIRouter(prefix="/api/transactions", tags=["Transaksi"])

# --- GANTI DENGAN SECRET KEY XENDIT ANDA (DARI DASHBOARD) ---
XENDIT_SECRET_KEY = "xnd_development_eJdk8FRAcnHpty49I9dZlxIY0h5ocSurbGwEeqLNn1k4uWBOQcXeNW3xO14PHo"

def get_xendit_headers():
    auth_str = f"{XENDIT_SECRET_KEY}:"
    b64_auth = base64.b64encode(auth_str.encode()).decode()
    return {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/json"
    }

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
    payment_method: str = Field(..., description="'cash' atau 'xendit'")
    amount_tendered: int
    discount_amount: int = 0
    voucher_discount_amount: int = 0
    items: List[TransactionItemCreate]

# ==========================================
# 2. ENDPOINT: CHECKOUT (BUAT TRANSAKSI & INVOICE XENDIT)
# ==========================================
@router.post("/checkout", summary="Proses Checkout (Bisa Cash atau Xendit)")
async def checkout(payload: TransactionCreate, db: Session = Depends(get_db)):
    try:
        # Hitung Subtotal
        calculated_subtotal = sum(((item.quantity * item.price) - item.item_discount) for item in payload.items)
        total_amount = max(0, calculated_subtotal - payload.discount_amount - payload.voucher_discount_amount)
        
        transaction_id = str(uuid.uuid4())
        date_str = datetime.now().strftime("%Y%m%d")
        receipt_number = f"TRX-{date_str}-{random.randint(1000, 9999)}"

        # Jika metode pembayaran Cash, langsung completed. Jika Xendit, status pending.
        initial_status = "completed" if payload.payment_method.lower() == "cash" else "pending"
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

        # ==========================================
        # JIKA BAYAR PAKAI XENDIT (Tembak API Xendit)
        # ==========================================
        if payload.payment_method.lower() == "xendit":
            xendit_payload = {
                "external_id": transaction_id, 
                "amount": total_amount,
                "description": f"Pembayaran Pesanan {receipt_number}",
                "invoice_duration": 86400, # Waktu kedaluwarsa 24 jam
                "customer": {"given_names": "Pelanggan Velo"}
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.xendit.co/v2/invoices",
                    headers=get_xendit_headers(),
                    json=xendit_payload,
                    timeout=10.0
                )
                
                if response.status_code != 200:
                    raise HTTPException(status_code=400, detail="Gagal membuat Invoice Xendit")
                    
                xendit_data = response.json()
                return {
                    "status": "success",
                    "message": "Menunggu Pembayaran",
                    "data": {
                        "transaction_id": transaction_id,
                        "receipt_number": receipt_number,
                        "invoice_url": xendit_data.get("invoice_url") # Link ini yang dibuka di Flutter
                    }
                }

        # Jika bayar Cash, langsung kembalikan sukses
        await manager.broadcast("REFRESH_TRANSAKSI")
        return {
            "status": "success",
            "message": "Transaksi berhasil disimpan",
            "data": {"transaction_id": transaction_id, "receipt_number": receipt_number}
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Gagal memproses transaksi: {str(e)}")

# ==========================================
# 3. ENDPOINT: WEBHOOK XENDIT (Jantung Otomatisasi)
# ==========================================
async def process_webhook_status(transaction_id: str, status: str, db: Session):
    try:
        if status == "PAID":
            # Ubah status menjadi completed
            db.execute(text("UPDATE transactions SET status = 'completed' WHERE id = :id"), {"id": transaction_id})
            db.commit()

            # Beri sinyal ke Flutter bahwa pembayaran sukses!
            await manager.broadcast(f"PAYMENT_SUCCESS_{transaction_id}")
            print(f"Transaksi {transaction_id} LUNAS.")

        elif status == "EXPIRED":
            # Ubah status menjadi cancelled karena invoice kedaluwarsa
            db.execute(text("UPDATE transactions SET status = 'cancelled' WHERE id = :id"), {"id": transaction_id})
            db.commit()

            # Beri sinyal ke Flutter agar kasir tahu pesanan hangus
            await manager.broadcast(f"PAYMENT_EXPIRED_{transaction_id}")
            print(f"Transaksi {transaction_id} KEDALUWARSA (Dibatalkan).")

    except Exception as e:
        db.rollback()
        print(f"Error background proses webhook: {e}")

@router.post("/xendit-webhook", summary="Penerima Notifikasi Pembayaran dari Xendit")
async def xendit_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    payload = await request.json()
    
    external_id = payload.get("external_id") # Ini berisi transaction_id
    status = payload.get("status") # Bisa "PAID" atau "EXPIRED"
    
    # Jika statusnya PAID (Lunas) atau EXPIRED (Hangus)
    if status in ["PAID", "EXPIRED"]:
        # Jalankan di background agar respon ke Xendit secepat mungkin
        background_tasks.add_task(process_webhook_status, external_id, status, db)
        
    return {"status": "success"} # Balas OK secepatnya ke Xendit