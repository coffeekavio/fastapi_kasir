from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Sesuaikan dengan user dan password VPS Anda
DATABASE_URL = "postgresql://admin_kasir:PasswordKuat123!@localhost:5432/kasir_db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Fungsi penyedia koneksi untuk setiap request (endpoint)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()