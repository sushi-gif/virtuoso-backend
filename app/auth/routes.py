from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, validator
from datetime import timedelta, datetime
from jose import jwt
from typing import Optional
from app.core.security import (
    SECRET_KEY, 
    ALGORITHM, 
    hash_password, 
    verify_password,
    verify_token
)
from app.db.database import database
from app.db.models import users
import re

router = APIRouter()

# Password validation regex
password_regex = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&]).{8,}$")

def validate_password(value: str) -> str:
    """Validates password complexity."""
    if not password_regex.match(value):
        raise ValueError(
            "Password must have at least 8 characters, including 1 uppercase, "
            "1 lowercase, 1 number, and 1 special character."
        )
    return value

# Authentication Models
class UserLogin(BaseModel):
    username: str
    password: str

# Input Models
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str 

    @validator("password")
    def password_validator(cls, value):
        return validate_password(value)

class UserEdit(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    password: Optional[str] = None

    @validator("password")
    def password_validator(cls, value):
        if value:
            return validate_password(value)
        return value

class AdminUserEdit(UserEdit):
    is_admin: Optional[bool] = None

# Output Models
class Token(BaseModel):
    access_token: str
    token_type: str

class User(BaseModel):
    id: int
    username: str
    email: str
    is_admin: Optional[bool]
    created_at: Optional[datetime] = None

    class Config:
        orm_mode = True

# Dependency Functions
async def get_current_user(token: dict = Depends(verify_token)):
    query = users.select().where(users.c.username == token["sub"])
    user = await database.fetch_one(query)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

async def get_admin_user(current_user: dict = Depends(get_current_user)):
    if not current_user["is_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    return current_user

# Authentication Endpoints
@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(user: UserCreate):
    existing = await database.fetch_one(
        users.select().where(
            (users.c.username == user.username) | 
            (users.c.email == user.email)
        )
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already exists"
        )

    hashed_pwd = hash_password(user.password)
    query = users.insert().values(
        username=user.username,
        email=user.email,
        hashed_password=hashed_pwd,
        is_admin=False
    )
    await database.execute(query)
    return {"message": "User created successfully"}

@router.post("/login", response_model=Token)
async def login(user: UserLogin):
    db_user = await database.fetch_one(
        users.select().where(users.c.username == user.username)
    )
    
    if not db_user or not verify_password(user.password, db_user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_expires = timedelta(minutes=1440)  # 24 hours
    access_token = jwt.encode(
        {
            "sub": db_user["username"],
            "exp": datetime.utcnow() + token_expires,
            "admin": db_user["is_admin"]
        },
        SECRET_KEY,
        algorithm=ALGORITHM
    )
    return {"access_token": access_token, "token_type": "bearer"}

# User Management Endpoints
@router.get("/users/me", response_model=User)
async def read_current_user(current_user: dict = Depends(get_current_user)):
    return current_user

@router.patch("/users/me", response_model=User)
async def update_current_user(
    user_data: UserEdit,
    current_user: dict = Depends(get_current_user)
):
    update_data = user_data.dict(exclude_unset=True)
    
    if "password" in update_data:
        update_data["hashed_password"] = hash_password(update_data.pop("password"))
    
    if update_data:
        query = (
            users.update()
            .where(users.c.id == current_user["id"])
            .values(**update_data)
        )
        await database.execute(query)
    
    return await database.fetch_one(
        users.select().where(users.c.id == current_user["id"])
    )

@router.get("/users", response_model=list[User])
async def search_users(
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    admin: dict = Depends(get_admin_user)
):
    query = users.select().limit(limit).offset(offset)
    if search:
        search = f"%{search}%"
        query = query.where(
            users.c.username.ilike(search) |
            users.c.email.ilike(search)
        )
    return await database.fetch_all(query)

@router.get("/users/{user_id}", response_model=User)
async def read_user(
    user_id: int,
    admin: dict = Depends(get_admin_user)
):
    user = await database.fetch_one(
        users.select().where(users.c.id == user_id)
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user

@router.patch("/users/{user_id}", response_model=User)
async def update_user(
    user_id: int,
    user_data: AdminUserEdit,
    admin: dict = Depends(get_admin_user)
):
    existing = await database.fetch_one(
        users.select().where(users.c.id == user_id)
    )
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    update_data = user_data.dict(exclude_unset=True)
    
    if "password" in update_data:
        update_data["hashed_password"] = hash_password(update_data.pop("password"))
    
    if update_data:
        query = (
            users.update()
            .where(users.c.id == user_id)
            .values(**update_data)
        )
        await database.execute(query)
    
    return await database.fetch_one(
        users.select().where(users.c.id == user_id)
    )

@router.delete("/users/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_current_user(current_user: dict = Depends(get_current_user)):
    query = users.delete().where(users.c.id == current_user["id"])
    await database.execute(query)
    return {"message": "Account deleted successfully"}

@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    admin: dict = Depends(get_admin_user)
):
    existing = await database.fetch_one(
        users.select().where(users.c.id == user_id)
    )
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    query = users.delete().where(users.c.id == user_id)
    await database.execute(query)
    return {"message": "User deleted successfully"}