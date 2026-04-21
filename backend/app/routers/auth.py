from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from sqlalchemy.exc import IntegrityError
from .. import models
from ..database import get_db
from ..utils.jwt import create_access_token
from ..utils.password import verify_password, hash_password
from ..dependencies import get_current_client

router = APIRouter(prefix="/auth", tags=["auth"])

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    name: Optional[str] = None  # Optional display name
    username: str
    password: str
    email: Optional[EmailStr] = None

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None

class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    client_id: int
    name: str


def _generate_unique_client_name(db: Session, base_name: str) -> str:
    seed = (base_name or "user").strip() or "user"
    candidate = seed
    suffix = 2
    while db.query(models.Client).filter(models.Client.name == candidate).first():
        candidate = f"{seed}-{suffix}"
        suffix += 1
    return candidate

@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and return JWT token. Pattern from VisionArk."""
    client = db.query(models.Client).filter(
        models.Client.username == req.username.lower(),
        models.Client.is_active == True
    ).first()
    
    if not client or not verify_password(req.password, client.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
    
    token = create_access_token(user_id=client.id, username=client.name)
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "client_id": client.id,
        "name": client.name
    }

@router.post("/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new client with login credentials."""
    username = req.username.strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    existing = db.query(models.Client).filter(models.Client.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")

    email = req.email.lower() if req.email else None
    if email:
        email_existing = db.query(models.Client).filter(models.Client.email == email).first()
        if email_existing:
            raise HTTPException(status_code=400, detail="Email already registered")

    client_name = _generate_unique_client_name(db, req.name or username)

    new_client = models.Client(
        name=client_name,
        username=username,
        email=email,
        password_hash=hash_password(req.password),
        ai_config={},
        general_settings={}
    )
    try:
        db.add(new_client)
        db.commit()
        db.refresh(new_client)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Unable to register with provided credentials")

    return {"message": "User registered successfully", "client_id": new_client.id}

@router.patch("/me")
def update_profile(
    req: ProfileUpdate, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Update user profile information. Pattern from VisionArk Settings."""
    if req.name:
        current_client.name = req.name
    if req.email:
        current_client.email = req.email
    if req.password:
        current_client.password_hash = hash_password(req.password)
    
    db.commit()
    return {"message": "Profile updated successfully"}
