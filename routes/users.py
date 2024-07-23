from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from database import get_database
from bson import ObjectId
from utils import create_access_token, create_refresh_token, decode_token, authenticate_user, get_password_hash, verify_password
from datetime import datetime, timedelta, timezone
from settings import settings
from models import User
from typing import Optional

router = APIRouter()

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    user_id: Optional[str] = None

class UserLogin(BaseModel):
    username: str
    password: str

# 사용자 생성 요청 모델 정의
class UserCreate(BaseModel):
    username: str
    password: str
    
# 리프레시 토큰 요청 모델 정의
class RefreshTokenRequest(BaseModel):
    refresh_token: str


# 로그인 : 비밀번호를 해싱
@router.post("/login", response_model=Token)
async def login_for_access_token(request: Request, db=Depends(get_database)):
    # JSON 데이터를 수신합니다.
    body = await request.json()
    user_login = UserLogin(**body)
    
    # 기존 로직을 사용합니다.
    user = await db.users.find_one({"username": user_login.username})
    if not user or not verify_password(user_login.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )
    refresh_token = create_refresh_token(data={"sub": user["username"]})
    
    # 리프레시 토큰을 DB에 저장
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"refresh_token": refresh_token}})
    
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer", "user_id": str(user["_id"])}

# RefreshToken을 사용하여 사용자에게 새로운 AccessToken을 반환
@router.post("/refresh", response_model=Token)
async def refresh_access_token(request: RefreshTokenRequest, db=Depends(get_database)):
    payload = await decode_token(request.refresh_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await db.users.find_one({"username": username})
    if not user or user.get("refresh_token") != request.refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "refresh_token": request.refresh_token, "token_type": "bearer"}



@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(user: UserCreate, db=Depends(get_database)):
    # 이미 존재하는 사용자인지 확인
    if await db.users.find_one({"username": user.username}):
        raise HTTPException(status_code=400, detail="Username already registered")
    
    # 비밀번호 해싱
    hashed_password = get_password_hash(user.password)
    user_data = user.dict()
    user_data["password"] = hashed_password
    user_data["created_at"] = datetime.utcnow()
    result = await db.users.insert_one(user_data)
    
    # 통계 데이터 초기화
    statistics_data = {
        "user_id": result.inserted_id,
        "weekly": [],
        "monthly": [],
        "yearly": [],
        "total_distance": {
            "year_start": datetime.now(timezone.utc),
            "distance": 0,
            "duration": 0,
            "count": 0,
            "average_pace": 0
        }
    }
    await db.statistics.insert_one(statistics_data)
    
    return {"id": str(result.inserted_id), "username": user.username}


@router.get("/me", response_model=User)
async def read_users_me(token: dict = Depends(decode_token), db=Depends(get_database)):
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username: str = token.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await db.users.find_one({"username": username})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
