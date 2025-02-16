from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import timedelta, datetime
from jose import jwt
from app.core.security import SECRET_KEY, ALGORITHM, hash_password, verify_password
from app.db.database import database
from app.db.models import users
from app.core.security import verify_token
from typing import Optional

router = APIRouter()

# Input models
class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class User(BaseModel):
    id: int
    username: str
    email: str
    is_admin: Optional[int]
    created_at: Optional[datetime]

# Output models
class Token(BaseModel):
    access_token: str
    token_type: str
    

@router.post("/signup")
async def signup(user: UserCreate):
    hashed_pwd = hash_password(user.password)
    query = users.insert().values(
        username=user.username, email=user.email, hashed_password=hashed_pwd
    )
    await database.execute(query)
    return {"msg": "User created successfully"}


@router.post("/login", response_model=Token)
async def login(user: UserLogin):
    query = users.select().where(users.c.username == user.username)
    db_user = await database.fetch_one(query)
    if not db_user or not verify_password(user.password, db_user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = jwt.encode(
        {"sub": db_user["username"], "exp": datetime.utcnow() + timedelta(minutes=1440*7)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    return {"access_token": access_token, "token_type": "bearer"}

# Your updated endpoint
@router.get("/user", response_model=User)
async def user(user=Depends(verify_token)):
    query = users.select().where(users.c.username == user['sub'])
    db_user = await database.fetch_one(query)

    if not db_user:
        raise HTTPException(status_code=400, detail="This shouldn't happen")

    # Map database result to Pydantic model
    return User(
        id=db_user["id"],
        username=db_user["username"],
        email=db_user["email"],
        is_admin=db_user["is_admin"],
        created_at=db_user["created_at"]
    )
