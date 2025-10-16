from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
import hmac
import hashlib
import base64
import uuid
from passlib.context import CryptContext
from fastapi import HTTPException, status
from pydantic import BaseModel

from nova_manager.core.config import (
    JWT_SECRET_KEY,
    PLAYGROUND_TOKEN_TTL_MINUTES,
)
from nova_manager.core.enums import UserRole

# Password hashing with bcrypt (12 rounds for security)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

# JWT settings
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 30


class AuthContext(BaseModel):
    """Auth context extracted from JWT token"""

    auth_user_id: str
    organisation_id: str
    app_id: Optional[str] = None  # Can be None before app creation
    email: str
    role: UserRole  # User role in the organization


PLAYGROUND_TOKEN_PREFIX = "nova_pg_"


class SDKAuthContext(BaseModel):
    """SDK auth context extracted from JWT token"""

    organisation_id: str
    app_id: str
    sdk_key: Optional[str] = None
    is_playground: bool = False
    playground_session_id: Optional[str] = None
    personalisation_id: Optional[str] = None
    user_id: Optional[str] = None


def hash_password(password: str) -> str:
    """Hash a password using bcrypt with salt"""

    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""

    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""

    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """Create a JWT refresh token (longer expiry)"""

    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update(
        {"exp": expire, "iat": datetime.now(timezone.utc), "type": "refresh"}
    )
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> dict:
    """Verify and decode a JWT token"""

    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


def decode_token_ignore_expiry(token: str) -> dict:
    """Decode JWT token ignoring expiration (for refresh operations)"""

    try:
        payload = jwt.decode(
            token, JWT_SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False}
        )
        return payload
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


def create_auth_context(payload: dict) -> AuthContext:
    """Create AuthContext from JWT payload"""

    return AuthContext(
        auth_user_id=payload.get("auth_user_id", ""),
        organisation_id=payload.get("organisation_id", ""),
        app_id=payload.get("app_id", ""),
        email=payload.get("email", ""),
        role=payload.get("role", "member"),
    )


# SDK API Key Functions for Client SDK Authentication
def create_sdk_api_key(organisation_id: str, app_id: str) -> str:
    """
    Create an ultra-compact stateless SDK API key for client SDK authentication.
    Uses binary UUID encoding + HMAC signature for maximum compression.
    
    Same org_id + app_id will always generate the same API key.
    
    Key format: nova_sk_<base64_encoded_payload_and_signature>
    Total length: ~67-73 characters
    
    Args:
        organisation_id: UUID string of the organisation
        app_id: UUID string of the app
        
    Returns:
        SDK API key in format: nova_sk_<api_key>
    """
    
    # Step 1: Convert UUID strings to binary format (16 bytes each)
    # This is the key compression - UUIDs go from 36 chars to 16 bytes
    try:
        org_uuid = uuid.UUID(organisation_id)
        app_uuid = uuid.UUID(app_id)
    except ValueError:
        raise ValueError(f"Invalid UUID format: org_id={organisation_id}, app_id={app_id}")
    
    # Step 2: Create binary payload (32 bytes total)
    org_bytes = org_uuid.bytes      # 16 bytes
    app_bytes = app_uuid.bytes      # 16 bytes  
    payload_bytes = org_bytes + app_bytes  # 32 bytes total
    
    # Step 3: Create HMAC-SHA256 signature for security and authenticity
    # Take first 12 bytes = 96 bits of security (industry standard)
    signature = hmac.new(
        JWT_SECRET_KEY.encode('utf-8'),
        payload_bytes,
        hashlib.sha256
    ).digest()[:12]  # 12 bytes = 96-bit security
    
    # Step 4: Combine payload + signature (44 bytes total)
    combined_data = payload_bytes + signature  # 32 + 12 = 44 bytes
    
    # Step 5: Base64 encode for text representation
    # 44 bytes → ~59 base64 characters (no padding)
    encoded = base64.urlsafe_b64encode(combined_data).decode('utf-8').rstrip('=')
    
    # Step 6: Add Nova SDK prefix
    # Final format: nova_sk_ (8 chars) + encoded (~59 chars) = ~67 chars total
    return f"nova_sk_{encoded}"


def validate_sdk_api_key(api_key: str) -> dict:
    """
    Validate an SDK API key and extract organisation_id and app_id.
    Ultra-fast stateless validation with no database lookups required.
    
    Validates HMAC signature and extracts binary UUIDs back to string format.
    Validation time: <1ms (vs 5-20ms for database-backed keys)
    
    Args:
        api_key: The SDK API key to validate

    Returns:
        Dict with organisation_id and app_id if valid, None if invalid
    """
    
    try:
        # Step 1: Basic format validation
        if not api_key.startswith("nova_sk_"):
            raise Exception("Invalid SDK API key format: missing nova_sk_ prefix")
        
        # Step 2: Extract base64 encoded data
        encoded = api_key[8:]  # Remove "nova_sk_" prefix
        
        if len(encoded) < 10:  # Sanity check for minimum length
            raise Exception("Invalid SDK API key format: too short")
        
        # Step 3: Base64 decode with padding restoration
        # Add padding if needed (base64 requires length divisible by 4)
        padding = 4 - (len(encoded) % 4)
        if padding != 4:
            encoded += '=' * padding
            
        try:
            combined_data = base64.urlsafe_b64decode(encoded)
        except Exception:
            raise Exception("Invalid SDK API key format: corrupted base64")
        
        # Step 4: Extract payload and signature
        if len(combined_data) != 44:  # Must be exactly 32 + 12 = 44 bytes
            raise Exception(f"Invalid SDK API key format: wrong length ({len(combined_data)} bytes, expected 44)")
        
        payload_bytes = combined_data[:32]    # First 32 bytes (2 UUIDs)
        provided_signature = combined_data[32:]  # Last 12 bytes (HMAC signature)
        
        # Step 5: Verify HMAC signature for authenticity
        expected_signature = hmac.new(
            JWT_SECRET_KEY.encode('utf-8'),
            payload_bytes,
            hashlib.sha256
        ).digest()[:12]
        
        # Use constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(provided_signature, expected_signature):
            raise Exception("Invalid SDK API key: signature verification failed")
        
        # Step 6: Extract and reconstruct UUIDs from binary format
        org_bytes = payload_bytes[:16]   # First 16 bytes
        app_bytes = payload_bytes[16:]   # Second 16 bytes
        
        try:
            org_uuid = uuid.UUID(bytes=org_bytes)
            app_uuid = uuid.UUID(bytes=app_bytes)
        except Exception:
            raise Exception("Invalid SDK API key: corrupted UUID data")
        
        # Step 7: Return extracted data in expected format
        return {
            "organisation_id": str(org_uuid),
            "app_id": str(app_uuid),
            "sdk_key": api_key,
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


def create_sdk_auth_context(payload: dict) -> SDKAuthContext:
    """
    Create SDKAuthContext for SDK API key authentication.

    Args:
        payload: Dict containing organisation_id and app_id

    Returns:
        SDKAuthContext configured for SDK authentication
    """

    return SDKAuthContext(
        organisation_id=payload.get("organisation_id", ""),
        app_id=payload.get("app_id", ""),
        sdk_key=payload.get("sdk_key"),
        is_playground=payload.get("type") == "playground",
        playground_session_id=payload.get("session_id"),
        personalisation_id=payload.get("personalisation_id"),
        user_id=payload.get("user_id"),
    )


def is_playground_token(token: str) -> bool:
    return token.startswith(PLAYGROUND_TOKEN_PREFIX)


def create_playground_session_token(
    *,
    session_id,
    organisation_id: str,
    app_id: str,
    personalisation_id,
    user_id,
    sdk_key: str,
    expires_at: datetime | None = None,
) -> str:
    issued_at = datetime.now(timezone.utc)
    expiry = expires_at

    if expiry is None and PLAYGROUND_TOKEN_TTL_MINUTES > 0:
        expiry = issued_at + timedelta(minutes=PLAYGROUND_TOKEN_TTL_MINUTES)

    payload = {
        "type": "playground",
        "session_id": str(session_id),
        "organisation_id": organisation_id,
        "app_id": app_id,
        "personalisation_id": str(personalisation_id),
        "user_id": str(user_id),
        "sdk_key": sdk_key,
        "iat": issued_at,
    }

    if expiry:
        payload["exp"] = expiry

    encoded = jwt.encode(payload, JWT_SECRET_KEY, algorithm=ALGORITHM)
    return f"{PLAYGROUND_TOKEN_PREFIX}{encoded}"


def validate_playground_session_token(token: str) -> dict:
    if not is_playground_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid playground token format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw = token[len(PLAYGROUND_TOKEN_PREFIX) :]

    try:
        payload = jwt.decode(raw, JWT_SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Playground session has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "playground":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid playground token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload
