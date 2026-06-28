from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session

from app.auth import get_current_user_id
from app.database import get_db
from app.models import User


def get_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登录")
    return authorization[7:]


def get_current_user(db: Session = Depends(get_db), token: str = Depends(get_token)) -> User:
    user_id = get_current_user_id(token)
    if not user_id:
        raise HTTPException(401, "登录已过期")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(401, "用户不存在")
    return user
