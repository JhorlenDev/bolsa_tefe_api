import requests
from django.conf import settings
from django.core.cache import cache


TOKEN_CACHE_KEY = 'tefe_access_token'
_SESSION = requests.Session()


def obter_token_tefe():
    cached_token = cache.get(TOKEN_CACHE_KEY)
    if cached_token:
        return cached_token

    response = _SESSION.post(
        settings.TEFE_TOKEN_URL,
        data={
            'grant_type': 'client_credentials',
            'client_id': settings.TEFE_CLIENT_ID,
            'client_secret': settings.TEFE_CLIENT_SECRET,
        },
        headers={
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        timeout=settings.TEFE_HTTP_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()
    access_token = data.get('access_token')

    if not access_token:
        raise Exception('access_token não encontrado na resposta do Keycloak.')

    expires_in = int(data.get('expires_in') or settings.TEFE_TOKEN_CACHE_TIMEOUT)
    cache_timeout = max(1, min(expires_in - 30, settings.TEFE_TOKEN_CACHE_TIMEOUT))
    cache.set(TOKEN_CACHE_KEY, access_token, cache_timeout)

    return access_token
