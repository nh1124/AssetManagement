from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Literal, Optional
from sqlalchemy.exc import IntegrityError
from .. import models
from ..database import get_db
from ..utils.jwt import create_access_token, create_typed_token, decode_token, decode_mcp_access_token, token_is_current
from ..utils.password import verify_password, hash_password
from ..dependencies import get_current_client, request_language, APPROVAL_PENDING, MCP_CONNECTION_ENDED
from ..domain.messages import Message, message_of, localize
from ..services import client_service, mcp_connection_service, mfa_service, system_settings_service

router = APIRouter(prefix="/auth", tags=["auth"])
INVALID_TOKEN = Message("Invalid token", ja="サインインの有効期限が切れました。もう一度サインインしてください。")
REAUTHENTICATION_REQUIRED = Message(
    "Reauthentication required", ja="本人確認ができませんでした。パスワードまたはコードを確認してください。",
)

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
    # Required to change the email or the password: a stolen session alone must not take the account.
    current_password: Optional[str] = None

class AuthResponse(BaseModel):
    access_token: Optional[str] = None
    token_type: Literal["step", "bearer"] = "bearer"
    client_id: int
    name: str
    next_step: Optional[Literal["password_change", "mfa_setup", "mfa"]] = None
    step_token: Optional[str] = None
    mfa_required: Optional[bool] = None
    mfa_token: Optional[str] = None


class MfaLoginVerifyRequest(BaseModel):
    mfa_token: str
    code: Optional[str] = None
    recovery_code: Optional[str] = None


class StepRequest(BaseModel):
    step_token: str


class PasswordChangeRequest(StepRequest):
    new_password: str


class EnrollVerifyRequest(StepRequest):
    code: str


class MfaSetupStartResponse(BaseModel):
    otpauth_uri: str
    manual_entry_key: str


class MfaSetupVerifyRequest(BaseModel):
    code: str


class MfaRecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class EnrollResponse(MfaRecoveryCodesResponse):
    access_token: str
    token_type: str = "bearer"
    client_id: int
    name: str


class MfaReplacementResponse(MfaRecoveryCodesResponse):
    access_token: str
    token_type: str = "bearer"


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


def _auth_response(client: models.Client) -> dict:
    token = create_access_token(user_id=client.id, username=client.name)
    return {
        "access_token": token,
        "token_type": "bearer",
        "client_id": client.id,
        "name": client.name,
        "mfa_required": False,
        "mfa_token": None,
    }


def _client_from_typed_token(db: Session, token: str, expected_type: str) -> models.Client:
    payload = decode_token(token)
    if not payload or payload.get("type") != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_TOKEN)

    client = client_service.get_active_by_id(db, payload.get("sub"))
    if not client or not token_is_current(payload, client.tokens_valid_after):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_TOKEN)
    if client.approval_pending:
        raise HTTPException(status_code=403, detail=APPROVAL_PENDING)
    return client

LOCKED = Message("Too many attempts. Try again later.", ja="試行が多すぎます。しばらくしてからもう一度お試しください。")
INVALID_MFA = Message("Invalid MFA code", ja="認証コードが正しくありません。")


def _ensure_unlocked(client: models.Client) -> None:
    if client_service.is_locked(client):
        raise HTTPException(status_code=429, detail=LOCKED)


def _failed(db: Session, client: models.Client, detail=INVALID_MFA, status_code: int = 401) -> None:
    client_service.record_auth_failure(db, client)
    _ensure_unlocked(client)
    raise HTTPException(status_code=status_code, detail=detail)


def _next_step(db: Session, client: models.Client) -> dict:
    if client.must_change_password:
        step = "password_change"
    elif not mfa_service.mfa_enabled(db, client.id):
        step = "mfa_setup"
    else:
        step = "mfa"
    token = create_typed_token(
        user_id=client.id, username=client.name, token_type=step,
        expires_delta=timedelta(minutes=5 if step == "mfa" else 10),
    )
    result = {
        "access_token": None, "token_type": "step", "client_id": client.id,
        "name": client.name, "next_step": step, "step_token": token,
    }
    if step == "mfa":
        result.update(mfa_required=True, mfa_token=token)
    return result


def _step_client(db: Session, token: str, step: str) -> models.Client:
    client = _client_from_typed_token(db, token, step)
    _ensure_unlocked(client)
    # Completed stages cannot be replayed to reset an enrolled factor or skip a required password change.
    enabled = mfa_service.mfa_enabled(db, client.id)
    if (step == "password_change" and not client.must_change_password
            or step != "password_change" and client.must_change_password
            or step == "mfa_setup" and enabled
            or step == "mfa" and not enabled):
        raise HTTPException(status_code=401, detail=INVALID_TOKEN)
    return client


@router.post("/login", response_model=AuthResponse, response_model_exclude_unset=True)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    client = client_service.get_by_username(db, req.username.lower(), active_only=True)
    invalid = Message("Invalid username or password", ja="ユーザー名またはパスワードが正しくありません。")
    if not client:
        raise HTTPException(status_code=401, detail=invalid)
    _ensure_unlocked(client)
    if not verify_password(req.password, client.password_hash or ""):
        _failed(db, client, invalid)
    if client.approval_pending:
        raise HTTPException(status_code=403, detail=APPROVAL_PENDING)
    return _next_step(db, client)


@router.post("/password-change", response_model=AuthResponse, response_model_exclude_unset=True)
def change_password(req: PasswordChangeRequest, db: Session = Depends(get_db)):
    client = _step_client(db, req.step_token, "password_change")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail=Message("Password must be at least 8 characters", ja="パスワードは8文字以上にしてください。"))
    if verify_password(req.new_password, client.password_hash or ""):
        raise HTTPException(status_code=400, detail=Message("New password must differ from the current password", ja="現在とは異なるパスワードを指定してください。"))
    client_service.change_password(db, client, hash_password(req.new_password))
    return _next_step(db, client)


@router.post("/enroll/start", response_model=MfaSetupStartResponse)
def start_enrollment(req: StepRequest, db: Session = Depends(get_db)):
    client = _step_client(db, req.step_token, "mfa_setup")
    result = mfa_service.start_totp_setup(db, client)
    return result


@router.post("/enroll/verify", response_model=EnrollResponse)
def verify_enrollment(req: EnrollVerifyRequest, db: Session = Depends(get_db)):
    client = _step_client(db, req.step_token, "mfa_setup")
    try:
        codes = mfa_service.verify_totp_setup(db, client, req.code)
    except ValueError as exc:
        _failed(db, client, message_of(exc), status_code=400)
    client_service.record_auth_success(db, client)
    return {"recovery_codes": codes, **_auth_response(client)}


@router.post("/mfa/login/verify", response_model=AuthResponse, response_model_exclude_unset=True)
def verify_mfa_login(req: MfaLoginVerifyRequest, db: Session = Depends(get_db)):
    client = _step_client(db, req.mfa_token, "mfa")
    if not mfa_service.verify_mfa_factor(db, client, code=req.code, recovery_code=req.recovery_code):
        _failed(db, client)
    client_service.record_auth_success(db, client)
    return _auth_response(client)


@router.post("/mcp/exchange", response_model=McpTokenExchangeResponse)
def exchange_mcp_token(req: McpTokenExchangeRequest, db: Session = Depends(get_db)):
    payload = decode_mcp_access_token(req.mcp_access_token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MCP access token")

    backend_client_id = payload.get("backend_client_id")
    username = str(payload.get("username") or payload.get("sub") or "").lower()
    if backend_client_id is not None:
        try:
            client_id = int(backend_client_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MCP subject is not a valid user")
        client = client_service.get_active_by_id(db, client_id)
    else:
        client = client_service.get_by_username(db, username, active_only=True)

    if not client or (username and (client.username or "").lower() != username):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MCP subject is not a valid user")

    if client.approval_pending:
        raise HTTPException(status_code=403, detail=APPROVAL_PENDING)

    if not token_is_current(payload, client.tokens_valid_after, claim="auth_time_ms", required=True):
        raise HTTPException(status_code=401, detail=INVALID_TOKEN)

    if not mfa_service.mfa_enabled(db, client.id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=Message("MFA setup required", ja="先にアプリで認証アプリを設定してください。"))

    mcp_client_id = str(payload.get("client_id") or "")
    # The token names its connection (WP35); one the person ended, or a token from
    # before connections were recorded, is refused here and at every backend request.
    connection_id = payload.get("cid")
    connection = (
        mcp_connection_service.active_connection(db, connection_id, client.id)
        if isinstance(connection_id, int) and not isinstance(connection_id, bool) else None
    )
    if connection is None or connection.oauth_client_id != mcp_client_id:
        raise HTTPException(status_code=401, detail=MCP_CONNECTION_ENDED)
    mcp_connection_service.record_use(db, connection)
    return {
        # chn=mcp binds the channel to the token: every request made with it is an AI
        # operation, gated and audited as one, whatever headers it carries (WP34).
        "access_token": create_typed_token(
            user_id=client.id,
            username=client.name,
            token_type="access",
            expires_delta=timedelta(minutes=15),
            extra_claims={"chn": "mcp", "mcp_client_id": mcp_client_id, "cid": connection.id},
        ),
        "token_type": "bearer",
        "client_id": client.id,
        "name": client.name,
        "username": client.username,
        "mcp_client_id": mcp_client_id,
    }

@router.post("/register", response_model=AuthResponse, response_model_exclude_unset=True)
def register(req: RegisterRequest, db: Session = Depends(get_db), request: Request = None):
    """Create a new client with login credentials."""
    registration_mode = system_settings_service.get(db, "registration_mode")
    if registration_mode == "closed":
        raise HTTPException(status_code=403, detail=Message("Sign-up is closed.", ja="現在、新規登録は受け付けていません。"))
    username = req.username.strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail=Message("Username is required", ja="ユーザー名を入力してください。"))
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail=Message("Password must be at least 8 characters", ja="パスワードは8文字以上にしてください。"))

    existing = client_service.get_by_username(db, username)
    if existing:
        raise HTTPException(status_code=400, detail=Message("Username already taken", ja="このユーザー名は使われています。"))

    email = req.email.lower() if req.email else None
    if email:
        email_existing = client_service.get_by_email(db, email)
        if email_existing:
            raise HTTPException(status_code=400, detail=Message("Email already registered", ja="このメールアドレスは登録済みです。"))

    client_name = client_service.unique_display_name(db, req.name or username)
    password_hash = hash_password(req.password)
    try:
        new_client = client_service.register(
            db, name=client_name, username=username, email=email,
            password_hash=password_hash, approval_pending=registration_mode == "approval",
        )
    except IntegrityError:
        raise HTTPException(status_code=400, detail=Message("Unable to register with provided credentials", ja="入力した内容では登録できませんでした。"))

    if new_client.approval_pending:
        return JSONResponse(status_code=202, content={"approval_pending": True, "message": localize(
            Message("Your account was created and is waiting for approval.", ja="アカウントを作成しました。管理者の承認をお待ちください。"),
            request_language(request) if request is not None else None)})
    return _next_step(db, new_client)


@router.get("/mfa/status")
def get_mfa_status(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return mfa_service.mfa_status(db, current_client)


@router.post("/mfa/replace/start", response_model=MfaSetupStartResponse)
def start_mfa_replacement(
    req: MfaFactorRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    _ensure_unlocked(current_client)
    if not mfa_service.verify_mfa_factor(db, current_client, code=req.code, recovery_code=req.recovery_code):
        _failed(db, current_client)
    result = mfa_service.start_totp_replacement(db, current_client)
    return result


@router.post("/mfa/replace/verify", response_model=MfaReplacementResponse)
def verify_mfa_replacement(
    req: MfaSetupVerifyRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    _ensure_unlocked(current_client)
    try:
        codes = mfa_service.verify_totp_replacement(db, current_client, req.code)
    except ValueError as exc:
        _failed(db, current_client, message_of(exc))
    client_service.revoke_tokens(db, current_client, commit=False)
    client_service.record_auth_success(db, current_client)
    return {"recovery_codes": codes, "access_token": create_access_token(current_client.id, current_client.name),
            "token_type": "bearer"}


@router.post("/mfa/recovery-codes/regenerate", response_model=MfaRecoveryCodesResponse)
def regenerate_recovery_codes(
    req: MfaFactorRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    _ensure_unlocked(current_client)
    if not mfa_service.verify_mfa_factor(db, current_client, code=req.code, recovery_code=req.recovery_code):
        _failed(db, current_client, REAUTHENTICATION_REQUIRED)
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
    _ensure_unlocked(current_client)
    # Step-up is MFA only: a password never stands in for the second factor.
    if not mfa_service.mfa_enabled(db, current_client.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=Message("MFA setup required", ja="先にMFAを設定してください。"))
    if not mfa_service.verify_mfa_factor(db, current_client, code=req.code, recovery_code=req.recovery_code):
        _failed(db, current_client, REAUTHENTICATION_REQUIRED)
    client_service.record_auth_success(db, current_client)
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
    """Update the account's name, email or password.

    Blank fields are left unchanged. The email and the password change only with the
    current password, so a session token alone cannot take over the account.
    """
    fields = {}
    if req.name and req.name.strip():
        fields["name"] = req.name.strip()
    if req.email and req.email.strip():
        fields["email"] = req.email.strip().lower()
    needs_password = "email" in fields or bool(req.password)
    if needs_password:
        _ensure_unlocked(current_client)
    if req.password:
        if len(req.password) < 8:
            raise HTTPException(status_code=422, detail=Message("パスワードは8文字以上にしてください。", en="Passwords need at least 8 characters."))
        fields["password_hash"] = hash_password(req.password)
    if needs_password:
        if not (req.current_password and verify_password(req.current_password, current_client.password_hash or "")):
            _failed(db, current_client, Message("The current password is incorrect.", ja="現在のパスワードが正しくありません。"), status_code=403)
    client_service.update_profile(db, current_client, fields)
    if needs_password:
        client_service.record_auth_success(db, current_client)
    response = {"message": "Profile updated successfully"}
    if "password_hash" in fields:
        response["access_token"] = create_access_token(current_client.id, current_client.name)
    return response
