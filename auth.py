import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def current_owner(request: Request,
                  credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
                  x_dev_user: Annotated[str | None, Header(max_length=100)] = None):
    settings = request.app.state.settings
    owner = None
    if settings.auth_mode == 'dev':
        owner = x_dev_user.strip() if x_dev_user else None
    elif credentials and credentials.scheme.lower() == 'bearer':
        for candidate, token in settings.api_tokens.items():
            if secrets.compare_digest(credentials.credentials.encode(), token.encode()):
                owner = candidate
    if not owner:
        raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Bearer'})
    request.state.owner_id = owner
    return owner
