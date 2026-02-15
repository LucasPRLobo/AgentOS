"""Google OAuth2 authentication helper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GoogleCredentials:
    """Holds Google OAuth2 tokens."""

    access_token: str = ""
    refresh_token: str = ""
    token_uri: str = "https://oauth2.googleapis.com/token"
    client_id: str = ""
    client_secret: str = ""
    scopes: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return bool(self.access_token)


def build_google_service(
    credentials: GoogleCredentials,
    service_name: str,
    version: str,
) -> Any:
    """Build a Google API service client.

    Requires google-api-python-client and google-auth to be installed.
    Returns the service object or raises ImportError.
    """
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ImportError(
            "Google API client not installed. "
            "Install with: pip install google-api-python-client google-auth"
        ) from exc

    creds = Credentials(
        token=credentials.access_token,
        refresh_token=credentials.refresh_token,
        token_uri=credentials.token_uri,
        client_id=credentials.client_id,
        client_secret=credentials.client_secret,
        scopes=credentials.scopes,
    )
    return build(service_name, version, credentials=creds)
