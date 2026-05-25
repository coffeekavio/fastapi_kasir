from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta

# Kunci rahasia untuk membuat token (Jangan disebar!)
SECRET_KEY = "kunci_rahasia_velo_super_aman_123" 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # Token aktif 24 jam

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12
)

def get_password_hash(password: str) -> str:
    """Hash password dengan bcrypt. Password akan otomatis truncate ke 72 bytes oleh passlib."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password dengan bcrypt."""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt