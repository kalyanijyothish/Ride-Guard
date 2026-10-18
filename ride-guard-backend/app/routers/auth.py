from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas import GoogleIn, LoginIn, RegisterIn, TokenOut, UserOut
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_out(user: User) -> TokenOut:
    return TokenOut(access_token=create_token(user.id, user.role), user=UserOut.model_validate(user))


def _login(db: Session, email: str, password: str) -> User:
    user = db.query(User).filter(User.email == email.lower()).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(403, "Account suspended")
    return user


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise HTTPException(409, "Email already registered")
    user = User(email=body.email.lower(), name=body.name, role=body.role,
                password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token_out(user)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    return _token_out(_login(db, body.email, body.password))


@router.post("/token", include_in_schema=False)
def token_form(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Used by the Swagger 'Authorize' button (username field = email)."""
    user = _login(db, form.username, form.password)
    return {"access_token": create_token(user.id, user.role), "token_type": "bearer"}


@router.post("/google", response_model=TokenOut)
def google_login(body: GoogleIn, db: Session = Depends(get_db)):
    """Sign in with Google: the Flutter app sends the Google ID token, we verify it."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(501, "Google sign-in not configured (set GOOGLE_CLIENT_ID)")
    from google.auth.transport import requests as greq
    from google.oauth2 import id_token
    try:
        info = id_token.verify_oauth2_token(body.id_token, greq.Request(), settings.GOOGLE_CLIENT_ID)
    except ValueError:
        raise HTTPException(401, "Invalid Google token")
    if not info.get("email_verified"):
        raise HTTPException(401, "Google email not verified")
    email = info["email"].lower()
    user = db.query(User).filter((User.google_sub == info["sub"]) | (User.email == email)).first()
    if user is None:
        user = User(email=email, name=info.get("name") or email.split("@")[0],
                    google_sub=info["sub"], role=body.role)
        db.add(user)
    elif not user.google_sub:
        user.google_sub = info["sub"]
    db.commit()
    db.refresh(user)
    if not user.is_active:
        raise HTTPException(403, "Account suspended")
    return _token_out(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
