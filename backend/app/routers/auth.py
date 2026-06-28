from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import authenticate_user, create_access_token, hash_password
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut
from app.services.api_key import has_api_key

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        deepseek_configured=has_api_key(user),
    )


@router.post("/register", response_model=TokenOut)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        from fastapi import HTTPException

        raise HTTPException(400, "邮箱已注册")
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        display_name=data.display_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_access_token(user.id), user=user_out(user))


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    from fastapi import HTTPException

    user = authenticate_user(db, data.email, data.password)
    if not user:
        raise HTTPException(401, "邮箱或密码错误")
    return TokenOut(access_token=create_access_token(user.id), user=user_out(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user_out(user)
