"""Auth routes: POST /auth/signup, POST /auth/login, GET /auth/me."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.database import get_users_collection
from app.schemas import (
    LoginRequest,
    LoginResponse,
    SignupRequest,
    UserResponse,
)
from app.security import (
    create_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Same message for a wrong email and a wrong password (requirement).
_UNAUTHORIZED = "Invalid email or password."

# A dummy hash used when the email is not found so a wrong-email attempt
# takes roughly as long as a wrong-password attempt.
_DUMMY_HASH = hash_password("dummy-password-for-timing-only")


@router.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(payload: SignupRequest):
    users = get_users_collection()
    if users.find_one({"email": payload.email}) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )
    user_doc = {
        "name": payload.name,
        "email": payload.email,
        "password_hash": hash_password(payload.password),
        "role": payload.role,
        "created_at": datetime.now(timezone.utc),
    }
    users.insert_one(user_doc)
    return UserResponse(
        name=user_doc["name"], email=user_doc["email"], role=user_doc["role"]
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    users = get_users_collection()
    user = users.find_one({"email": payload.email})
    if user is None:
        # Run a dummy verification to keep timing similar, then 401.
        verify_password(payload.password, _DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_UNAUTHORIZED
        )
    if not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_UNAUTHORIZED
        )
    token = create_token(user["email"], user["role"])
    return LoginResponse(
        token=token,
        user=UserResponse(
            name=user["name"], email=user["email"], role=user["role"]
        ),
    )


@router.get("/me", response_model=UserResponse)
def me(user: dict = Depends(get_current_user)):
    return UserResponse(
        name=user["name"], email=user["email"], role=user["role"]
    )
