from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_user
from app.core.security import create_access_token,hash_password,verify_password
from app.core.db import get_db
from app.models.user import user,UserRole
from app.schemas.user import UserRegister
from app.schemas.auth import AuthResponse,UserLogin


