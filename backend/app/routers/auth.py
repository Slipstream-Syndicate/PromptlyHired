from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.models import JobPreferences, RefreshToken, User
from app.rate_limit import login_rate_limit, refresh_rate_limit, signup_rate_limit
from app.schemas import RefreshRequest, TokenPair, UserCreate, UserLogin, UserOut
from app.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Hashing a throwaway value on a failed login keeps response time roughly
# constant whether or not the email exists, so timing cannot enumerate users.
_DUMMY_HASH = hash_password("not-a-real-password")


def _issue_tokens(db, user: User) -> TokenPair:
    raw_refresh, token_hash, expires_at = generate_refresh_token()
    db.add(RefreshToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at))
    db.commit()
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=raw_refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post(
    "/signup",
    response_model=TokenPair,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(signup_rate_limit)],
)
def signup(payload: UserCreate, db: DbSession) -> TokenPair:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )

    user = User(email=email, password_hash=hash_password(payload.password), name=payload.name)
    db.add(user)
    db.flush()
    # Empty preferences up front so the profile and homepage filters always
    # have a row to read and write.
    db.add(JobPreferences(user_id=user.id))
    db.commit()
    db.refresh(user)
    return _issue_tokens(db, user)


@router.post("/login", response_model=TokenPair, dependencies=[Depends(login_rate_limit)])
def login(payload: UserLogin, db: DbSession) -> TokenPair:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None:
        verify_password(payload.password, _DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password."
        )
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password."
        )
    return _issue_tokens(db, user)


@router.post("/refresh", response_model=TokenPair, dependencies=[Depends(refresh_rate_limit)])
def refresh(payload: RefreshRequest, db: DbSession) -> TokenPair:
    """Rotate the refresh token - the presented one is revoked on use."""
    token = db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(payload.refresh_token)
        )
    )
    now = datetime.now(timezone.utc)
    if token is None or token.revoked or token.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token."
        )

    user = db.get(User, token.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token."
        )

    token.revoked = True
    return _issue_tokens(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, db: DbSession) -> None:
    token = db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(payload.refresh_token)
        )
    )
    if token is not None:
        token.revoked = True
        db.commit()


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
