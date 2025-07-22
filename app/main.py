import hashlib
import os
from typing import List

from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import models, database

# --- Azure Monitor / OpenTelemetry -----------------------------------------
AI_CONN = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
if AI_CONN:
    # Auto-enable traces, metrics and logs export to App Insights
    from azure.monitor.opentelemetry import configure_azure_monitor
    configure_azure_monitor(connection_string=AI_CONN)

    # Optional: custom spans / metrics
    from opentelemetry import trace, metrics

    tracer = trace.get_tracer("fintech.api")
    meter = metrics.get_meter("fintech.api")
    users_registered = meter.create_counter(
        "users_registered", description="Number of users successfully registered"
    )
    tx_created = meter.create_counter(
        "transactions_created", description="Number of transactions created"
    )
else:
    tracer = None
    users_registered = None
    tx_created = None
# ---------------------------------------------------------------------------

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
    """Hash password using SHA-256 (use bcrypt in production)."""
    return hashlib.sha256(password.encode()).hexdigest()


@app.get("/")
def read_root():
    return {"message": "FinTech API is running"}


@app.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(database.get_db)):
    span_ctx = tracer.start_as_current_span("register_user") if tracer else nullcontext()
    with span_ctx:
        existing_user = (
            db.query(models.User).filter(models.User.username == user.username).first()
        )
        if existing_user:
            raise HTTPException(status_code=400, detail="Username already registered")

        hashed_password = hash_password(user.password)
        db_user = models.User(username=user.username, password=hashed_password)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        if users_registered:
            users_registered.add(1)

        return db_user


@app.post("/transactions", response_model=TransactionResponse)
def create_transaction(tx: TransactionCreate, db: Session = Depends(database.get_db)):
    span_ctx = tracer.start_as_current_span("create_transaction") if tracer else nullcontext()
    with span_ctx:
        user = db.query(models.User).filter(models.User.id == tx.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        db_tx = models.Transaction(
            amount=tx.amount, description=tx.description, user_id=tx.user_id
        )
        db.add(db_tx)
        db.commit()
        db.refresh(db_tx)

        if tx_created:
            tx_created.add(1, {"user_id": str(tx.user_id)})

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


# Utility for when tracer is None (local/no AI)
from contextlib import nullcontext  # at bottom to avoid circular import error
