from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from . import models, database
from pydantic import BaseModel
from typing import List
import hashlib
import os

app = FastAPI(title="Healerkay FinTech API", version="1.0.0")

# Create tables
models.Base.metadata.create_all(bind=database.engine)

class UserCreate(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True

class TransactionCreate(BaseModel):
    amount: float
    description: str
    user_id: int

class TransactionResponse(BaseModel):
    id: int
    amount: float
    description: str
    user_id: int

    class Config:
        from_attributes = True

def hash_password(password: str) -> str:
    """Hash password using SHA-256 (use bcrypt in production)"""
    return hashlib.sha256(password.encode()).hexdigest()

@app.get("/")
def read_root():
    return {"message": "FinTech API is running"}

@app.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(database.get_db)):
    # Check if user already exists
    existing_user = db.query(models.User).filter(models.User.username == user.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    # Hash password before storing
    hashed_password = hash_password(user.password)
    db_user = models.User(username=user.username, password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.post("/transactions", response_model=TransactionResponse)
def create_transaction(tx: TransactionCreate, db: Session = Depends(database.get_db)):
    # Validate user exists
    user = db.query(models.User).filter(models.User.id == tx.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db_tx = models.Transaction(amount=tx.amount, description=tx.description, user_id=tx.user_id)
    db.add(db_tx)
    db.commit()
    db.refresh(db_tx)
    return db_tx

@app.get("/transactions", response_model=List[TransactionResponse])
def get_transactions(db: Session = Depends(database.get_db)):
    return db.query(models.Transaction).all()

@app.get("/users/{user_id}/transactions", response_model=List[TransactionResponse])
def get_user_transactions(user_id: int, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return db.query(models.Transaction).filter(models.Transaction.user_id == user_id).all()
