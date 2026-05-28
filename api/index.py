from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List
import os
from database import get_db
from .auth import verify_password, create_access_token, get_password_hash
from .routes import kategori_router, menu_router, ingredients_router, stock_opname_router, members_router, vouchers_router
from .websockets import router as websocket_router

app = FastAPI(
    title="Management Karyawan API",
    description="Backend API untuk sistem management karyawan menggunakan FastAPI dan Supabase Auth",
    version="1.1.0"
)

# 1. KONFIGURASI CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://management-kasir.pages.dev",  # URL Produksi Vercel Anda
        "http://localhost:3000"                  # URL Lokal untuk development
    ],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. VALIDASI SKEMA DATA (PYDANTIC MODELS)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class LoginUsernameRequest(BaseModel):
    username: str
    password: str

class CreateCafeRequest(BaseModel):
    name: str = Field(..., min_length=2, description="Nama kafe/outlet baru")
    address: Optional[str] = Field(None, description="Alamat lokasi kafe")
    manager_id: Optional[str] = Field(None, description="ID manager yang mengelola kafe")

class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, description="Password minimal 6 karakter")
    username: str = Field(..., min_length=3, description="Username unik pengguna")
    full_name: str = Field(..., description="Nama lengkap pengguna")
    role: str = Field(..., description="Role wajib diisi: 'manager', 'supervisor', atau 'kasir'")
    cafe_id: Optional[str] = Field(None, description="ID kafe (opsional untuk manager)")

class UpdateUserRequest(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6)
    username: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None

# 3. ENDPOINT: LOGIN EMAIL (UNTUK KOMPATIBILITAS)
@app.post("/api/auth/login", summary="Login menggunakan Email dan Password")
def login_with_email(payload: LoginRequest, db: Session = Depends(get_db)):
    """
    Login menggunakan email dan password.
    Mencari user berdasarkan email di database lokal.
    """
    try:
        # Cari user berdasarkan email
        query = text("SELECT id, username, email, full_name, role, cafe_id, hashed_password FROM users WHERE email = :email")
        result = db.execute(query, {"email": payload.email}).fetchone()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email atau password salah."
            )

        # Verifikasi password
        if not verify_password(payload.password, result.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email atau password salah."
            )

        # Buat token JWT
        token_data = {"sub": result.email, "id": str(result.id), "role": result.role}
        access_token = create_access_token(data=token_data)

        return {
            "status": "success",
            "message": "Login berhasil",
            "user": {
                "id": result.id,
                "email": result.email,
                "username": result.username,
                "name": result.full_name,
                "role": result.role,
                "cafe_id": result.cafe_id
            },
            "token": access_token
        }
    except HTTPException as http_e:
        raise http_e
    except Exception as e:
        print(f"DEBUG: Login error - {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email atau password salah."
        )

# 4. ENDPOINT: LOGIN USERNAME
@app.post("/api/auth/login-username", summary="Login menggunakan Username dan Password")
def login_with_username(payload: LoginUsernameRequest, db: Session = Depends(get_db)):
    """
    Login menggunakan username dan password.
    Mencari user berdasarkan username di database lokal.
    """
    try:
        # Cari user berdasarkan username
        query = text("SELECT id, username, email, full_name, role, cafe_id, hashed_password FROM users WHERE username = :username")
        result = db.execute(query, {"username": payload.username}).fetchone()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Username atau password salah."
            )

        # Verifikasi password
        if not verify_password(payload.password, result.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Username atau password salah."
            )

        # Buat token JWT
        token_data = {"sub": result.username, "id": str(result.id), "role": result.role}
        access_token = create_access_token(data=token_data)

        return {
            "status": "success",
            "message": "Login berhasil",
            "user": {
                "id": result.id,
                "username": result.username,
                "email": result.email,
                "name": result.full_name,
                "role": result.role,
                "cafe_id": result.cafe_id
            },
            "token": access_token
        }
    except HTTPException as http_e:
        raise http_e
    except Exception as e:
        print(f"DEBUG: Login username error - {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username atau password salah."
        )

# 5. ENDPOINT: MEMBUAT KAFE BARU (LANGKAH 1)
@app.post("/create-cafes", summary="Langkah 1: Membuat data kafe baru di sistem")
def create_cafe(payload: CreateCafeRequest, db: Session = Depends(get_db)):
    try:
        # Insert data kafe ke database
        insert_query = text("""
            INSERT INTO cafes (name, address, manager_id)
            VALUES (:name, :address, :manager_id)
            RETURNING id, name, address, manager_id
        """)
        
        result = db.execute(insert_query, {
            "name": payload.name,
            "address": payload.address,
            "manager_id": payload.manager_id
        }).fetchone()
        
        if not result:
            raise HTTPException(status_code=400, detail="Gagal menyimpan data kafe.")
        
        cafe_id = result.id
        
        # AUTO-INSERT DEFAULT MEMBER SETTINGS untuk cafe yang baru dibuat
        # Default: Rp 10.000 = 1 poin, 100 poin = 10% diskon
        try:
            default_settings_query = text("""
                INSERT INTO member_settings (cafe_id, earning_amount, earning_points, redemption_points, redemption_discount)
                VALUES (:cafe_id, :earning_amount, :earning_points, :redemption_points, :redemption_discount)
                ON CONFLICT (cafe_id) 
                DO NOTHING
            """)
            
            db.execute(default_settings_query, {
                "cafe_id": cafe_id,
                "earning_amount": 10000,
                "earning_points": 1,
                "redemption_points": 100,
                "redemption_discount": 10
            })
            
            db.commit()
        except Exception as settings_error:
            print(f"DEBUG: Auto-insert member settings error - {str(settings_error)}")
            # Jangan fail jika settings gagal, cafe tetap dibuat
        
        return {
            "status": "success",
            "message": f"Kafe '{result.name}' berhasil didaftarkan dengan default member settings!",
            "data": {
                "cafe_id": result.id,
                "cafe_name": result.name,
                "manager_id": result.manager_id,
                "member_settings": {
                    "earning_amount": 10000,
                    "earning_points": 1,
                    "redemption_points": 100,
                    "redemption_discount": 10,
                    "description": "Setiap Rp 10.000 belanja = 1 poin | 100 poin = 10% diskon"
                }
            }
        }
    except HTTPException as http_e:
        db.rollback()
        raise http_e
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Create cafe error - {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


# 6. ENDPOINT: PEMBUATAN USER (LANGKAH 2)
@app.post("/create-user", summary="Langkah 2: Membuat akun user (Manager/Supervisor/Kasir)")
def create_user(payload: CreateUserRequest, db: Session = Depends(get_db)):
    role_lower = payload.role.lower()
    if role_lower not in ["manager", "supervisor", "kasir"]:
        raise HTTPException(status_code=400, detail="Role tidak valid.")
    
    # Validasi: supervisor dan kasir harus memiliki cafe_id
    if role_lower in ["supervisor", "kasir"] and not payload.cafe_id:
        raise HTTPException(status_code=400, detail="cafe_id wajib diisi untuk supervisor dan kasir.")

    try:
        # Hash password (passlib will handle bcrypt's 72-byte limit automatically)
        hashed_password = get_password_hash(payload.password)
        
        # Insert user ke database dengan ID otomatis
        insert_query = text("""
            INSERT INTO users (id, email, username, full_name, role, cafe_id, hashed_password)
            VALUES (gen_random_uuid(), :email, :username, :full_name, :role, :cafe_id, :hashed_password)
            RETURNING id, username, email, full_name, role, cafe_id
        """)
        
        result = db.execute(insert_query, {
            "email": payload.email,
            "username": payload.username,
            "full_name": payload.full_name,
            "role": role_lower,
            "cafe_id": payload.cafe_id,
            "hashed_password": hashed_password
        }).fetchone()
        
        db.commit()
        
        if not result:
            raise HTTPException(status_code=400, detail="Gagal membuat akun pengguna.")

        return {
            "status": "success",
            "message": f"Akun dengan role '{role_lower}' berhasil dibuat!",
            "data": {
                "user_id": result.id,
                "username": result.username,
                "email": result.email,
                "role": role_lower,
                "cafe_id": result.cafe_id
            }
        }
    except HTTPException as http_e:
        db.rollback()
        raise http_e
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Create user error - {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/users")
def get_employees(cafe_id: str, db: Session = Depends(get_db)):
    try:
        # Query untuk mendapatkan karyawan (supervisor dan kasir) berdasarkan cafe_id
        query = text("""
            SELECT id, username, email, full_name, role, cafe_id, created_at
            FROM users
            WHERE cafe_id = :cafe_id AND role IN ('supervisor', 'kasir')
            ORDER BY created_at DESC
        """)
        
        results = db.execute(query, {"cafe_id": cafe_id}).mappings().fetchall()
        
        return {
            "status": "success",
            "data": [dict(row) for row in results]
        }
    except Exception as e:
        print(f"DEBUG: Get employees error - {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# 7. ENDPOINT: EDIT DATA KARYAWAN
@app.put("/api/users/{user_id}", summary="Memperbarui data akun karyawan")
def update_employee(user_id: str, payload: UpdateUserRequest, db: Session = Depends(get_db)):
    try:
        # Build update query dinamis berdasarkan field yang diisi
        update_data = {}
        
        if payload.username:
            update_data["username"] = payload.username
        if payload.full_name:
            update_data["full_name"] = payload.full_name
        if payload.email:
            update_data["email"] = payload.email
        if payload.role:
            update_data["role"] = payload.role.lower()
        if payload.password:
            update_data["hashed_password"] = get_password_hash(payload.password)

        if not update_data:
            raise HTTPException(status_code=400, detail="Tidak ada data yang diperbarui")

        # Build SQL update statement
        set_clause = ", ".join([f"{key} = :{key}" for key in update_data.keys()])
        update_query = text(f"""
            UPDATE users
            SET {set_clause}
            WHERE id = :id
            RETURNING id, username, email, full_name, role, cafe_id
        """)
        
        update_data["id"] = user_id
        result = db.execute(update_query, update_data).fetchone()
        db.commit()
        
        if not result:
            raise HTTPException(status_code=404, detail="User tidak ditemukan")

        return {
            "status": "success",
            "message": "Data karyawan berhasil diperbarui",
            "data": dict(result._mapping) if result else None
        }
    except HTTPException as http_e:
        db.rollback()
        raise http_e
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Update employee error - {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Gagal memperbarui data: {str(e)}"
        )


# 8. ENDPOINT: HAPUS AKUN KARYAWAN
@app.delete("/api/users/{user_id}", summary="Menghapus akun karyawan dari sistem")
def delete_employee(user_id: str, db: Session = Depends(get_db)):
    try:
        delete_query = text("DELETE FROM users WHERE id = :id")
        result = db.execute(delete_query, {"id": user_id})
        db.commit()
        
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User tidak ditemukan")
        
        return {
            "status": "success",
            "message": "Akun karyawan berhasil dihapus dari sistem"
        }
    except HTTPException as http_e:
        db.rollback()
        raise http_e
    except Exception as e:
        db.rollback()
        print(f"DEBUG: Delete employee error - {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Gagal menghapus akun: {str(e)}"
        )

@app.get("/api/cafes", summary="Mengambil daftar kafe/cabang milik seorang Manager")
def get_manager_cafes(manager_id: str, db: Session = Depends(get_db)):
    try:
        query = text("""
            SELECT id, name, address, manager_id, created_at 
            FROM cafes 
            WHERE manager_id = :manager_id
        """)
        results = db.execute(query, {"manager_id": manager_id}).mappings().fetchall()
        
        return {
            "status": "success", 
            "data": [dict(row) for row in results]
        }
    except Exception as e:
        print(f"DEBUG: Get manager cafes error - {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Inisiasi rute
app.include_router(kategori_router)
app.include_router(menu_router)
app.include_router(ingredients_router)
app.include_router(stock_opname_router)
app.include_router(members_router)
app.include_router(vouchers_router)
app.include_router(websocket_router, prefix="/api")