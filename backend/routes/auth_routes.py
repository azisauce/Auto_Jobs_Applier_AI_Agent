"""Auth routes — login and logout."""

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from backend.auth import APP_USERNAME, verify_password, create_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    message: str
    username: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, response: Response):
    if body.username != APP_USERNAME or not verify_password(body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_access_token(body.username)

    # Set httpOnly, secure cookie
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24,  # 24 hours
        path="/",
    )

    return LoginResponse(message="Login successful", username=body.username)


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key="access_token", path="/")
    return {"message": "Logged out"}


@router.get("/me")
async def me():
    """Quick check if the user is authenticated — called by the frontend auth guard.
    The actual auth check is done by the get_current_user dependency on this route."""
    from backend.auth import get_current_user
    # This endpoint is protected at the router level in main.py
    return {"authenticated": True}
