from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from sqlalchemy.exc import IntegrityError
from .. import models
from ..database import get_db
from ..utils.jwt import create_access_token, create_typed_token, decode_token, decode_mcp_access_token
from ..utils.password import verify_password, hash_password
from ..dependencies import get_current_client
from ..services import mfa_service

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
    access_token: Optional[str] = None
    token_type: str = "bearer"
    client_id: int
    name: str
    mfa_required: bool = False
    mfa_token: Optional[str] = None


class MfaLoginVerifyRequest(BaseModel):
    mfa_token: str
    code: Optional[str] = None
    recovery_code: Optional[str] = None


class MfaStartRequest(BaseModel):
    current_password: str


class MfaSetupStartResponse(BaseModel):
    otpauth_uri: str
    manual_entry_key: str


class MfaSetupVerifyRequest(BaseModel):
    code: str


class MfaRecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class MfaFactorRequest(BaseModel):
    current_password: Optional[str] = None
    code: Optional[str] = None
    recovery_code: Optional[str] = None


class StepUpResponse(BaseModel):
    step_up_token: str
    token_type: str = "step_up"
    expires_in_seconds: int = 600


class McpTokenExchangeRequest(BaseModel):
    mcp_access_token: str


class McpTokenExchangeResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    client_id: int
    name: str
    username: Optional[str] = None
    mcp_client_id: str


def _generate_unique_client_name(db: Session, base_name: str) -> str:
    seed = (base_name or "user").strip() or "user"
    candidate = seed
    suffix = 2
    while db.query(models.Client).filter(models.Client.name == candidate).first():
        candidate = f"{seed}-{suffix}"
        suffix += 1
    return candidate


def _auth_response(client: models.Client) -> dict:
    token = create_access_token(user_id=client.id, username=client.name)
    return {
        "access_token": token,
        "token_type": "bearer",
        "client_id": client.id,
        "name": client.name,
        "mfa_required": False,
    }


def _client_from_typed_token(db: Session, token: str, expected_type: str) -> models.Client:
    payload = decode_token(token)
    if not payload or payload.get("type") != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    client = db.query(models.Client).filter(
        models.Client.id == payload.get("sub"),
        models.Client.is_active == True,
    ).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return client

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
    
    mfa_setting = mfa_service.get_mfa_setting(db, client)
    if mfa_setting and mfa_setting.enabled:
        mfa_token = create_typed_token(
            user_id=client.id,
            username=client.name,
            token_type="mfa",
            expires_delta=timedelta(minutes=5),
        )
        return {
            "access_token": None,
            "token_type": "mfa",
            "client_id": client.id,
            "name": client.name,
            "mfa_required": True,
            "mfa_token": mfa_token,
        }

    return _auth_response(client)


@router.post("/mfa/login/verify", response_model=AuthResponse)
def verify_mfa_login(req: MfaLoginVerifyRequest, db: Session = Depends(get_db)):
    client = _client_from_typed_token(db, req.mfa_token, "mfa")
    if not mfa_service.verify_mfa_factor(db, client, code=req.code, recovery_code=req.recovery_code):
        # TODO(P1-002): connect MFA failure to audit log service.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA code")
    return _auth_response(client)


@router.post("/mcp/exchange", response_model=McpTokenExchangeResponse)
def exchange_mcp_token(req: McpTokenExchangeRequest, db: Session = Depends(get_db)):
    payload = decode_mcp_access_token(req.mcp_access_token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MCP access token")

    backend_client_id = payload.get("backend_client_id")
    username = str(payload.get("username") or payload.get("sub") or "").lower()
    query = db.query(models.Client).filter(models.Client.is_active == True)
    if backend_client_id is not None:
        try:
            client_id = int(backend_client_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MCP subject is not a valid user")
        client = query.filter(models.Client.id == client_id).first()
    else:
        client = query.filter(models.Client.username == username).first()

    if not client or (username and (client.username or "").lower() != username):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MCP subject is not a valid user")

    return {
        "access_token": create_typed_token(
            user_id=client.id,
            username=client.name,
            token_type="access",
            expires_delta=timedelta(minutes=15),
        ),
        "token_type": "bearer",
        "client_id": client.id,
        "name": client.name,
        "username": client.username,
        "mcp_client_id": str(payload.get("client_id") or ""),
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


@router.get("/mfa/status")
def get_mfa_status(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return mfa_service.mfa_status(db, current_client)


@router.post("/mfa/setup/start", response_model=MfaSetupStartResponse)
def start_mfa_setup(
    req: MfaStartRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if not verify_password(req.current_password, current_client.password_hash or ""):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    return mfa_service.start_totp_setup(db, current_client)


@router.post("/mfa/setup/verify", response_model=MfaRecoveryCodesResponse)
def verify_mfa_setup(
    req: MfaSetupVerifyRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        codes = mfa_service.verify_totp_setup(db, current_client, req.code)
    except ValueError as exc:
        # TODO(P1-002): connect MFA setup failures to audit log service.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"recovery_codes": codes}


@router.post("/mfa/disable")
def disable_mfa(
    req: MfaFactorRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if not mfa_service.verify_reauth_factor(
        db,
        current_client,
        current_password=req.current_password,
        code=req.code,
        recovery_code=req.recovery_code,
    ):
        # TODO(P1-002): connect MFA disable failures to audit log service.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Reauthentication required")

    mfa_service.disable_mfa(db, current_client)
    return {"message": "MFA disabled"}


@router.post("/mfa/recovery-codes/regenerate", response_model=MfaRecoveryCodesResponse)
def regenerate_recovery_codes(
    req: MfaFactorRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if not mfa_service.verify_reauth_factor(
        db,
        current_client,
        current_password=req.current_password,
        code=req.code,
        recovery_code=req.recovery_code,
    ):
        # TODO(P1-002): connect recovery-code regeneration failures to audit log service.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Reauthentication required")

    setting = mfa_service.get_mfa_setting(db, current_client)
    if not setting or not setting.enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not enabled")
    return {"recovery_codes": mfa_service.regenerate_recovery_codes(db, current_client)}


def _issue_step_up_token(client: models.Client) -> dict:
    return {
        "step_up_token": create_typed_token(
            user_id=client.id,
            username=client.name,
            token_type="step_up",
            expires_delta=timedelta(minutes=10),
        ),
        "token_type": "step_up",
        "expires_in_seconds": 600,
    }


@router.post("/reauth", response_model=StepUpResponse)
def reauth(
    req: MfaFactorRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if not mfa_service.verify_reauth_factor(
        db,
        current_client,
        current_password=req.current_password,
        code=req.code,
        recovery_code=req.recovery_code,
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Reauthentication required")
    return _issue_step_up_token(current_client)


@router.post("/step-up/verify", response_model=StepUpResponse)
def verify_step_up(
    req: MfaFactorRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return reauth(req=req, db=db, current_client=current_client)

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
