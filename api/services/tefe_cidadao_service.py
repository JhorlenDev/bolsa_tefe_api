import requests
from django.conf import settings
from django.core.cache import cache
from .tefe_auth_service import obter_token_tefe

_SESSION = requests.Session()


def _normalizar_cpf(cpf):
    return ''.join(char for char in str(cpf or '') if char.isdigit())


def _cache_key_para_cpf(cpf):
    return f"tefe_cidadao:{_normalizar_cpf(cpf)}"


def buscar_cidadao_por_cpf(cpf):
    cpf = _normalizar_cpf(cpf)
    cache_key = _cache_key_para_cpf(cpf)
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    token = obter_token_tefe()

    first = 0
    max_results = 100

    while True:
        response = _SESSION.get(
            settings.TEFE_CIDADAO_BUSCA_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            params={
                "first": first,
                "max": max_results,
            },
            timeout=settings.TEFE_HTTP_TIMEOUT,
        )

        response.raise_for_status()

        usuarios = response.json()

        if not usuarios:
            break

        for usuario in usuarios:
            atributos = usuario.get("attributes") or {}
            cpf_attr = atributos.get("cpf")

            if isinstance(cpf_attr, list) and cpf in cpf_attr:
                result = {
                    "id": usuario.get("id"),
                    "username": usuario.get("username"),
                    "email": usuario.get("email"),
                    "first_name": usuario.get("firstName"),
                    "last_name": usuario.get("lastName"),
                    "cpf": cpf,
                    "attributes": atributos,
                }
                cache.set(cache_key, result, settings.TEFE_CIDADAO_CACHE_TIMEOUT)
                return result

            if isinstance(cpf_attr, str) and cpf_attr == cpf:
                result = {
                    "id": usuario.get("id"),
                    "username": usuario.get("username"),
                    "email": usuario.get("email"),
                    "first_name": usuario.get("firstName"),
                    "last_name": usuario.get("lastName"),
                    "cpf": cpf,
                    "attributes": atributos,
                }
                cache.set(cache_key, result, settings.TEFE_CIDADAO_CACHE_TIMEOUT)
                return result

        if len(usuarios) < max_results:
            break

        first += max_results

    raise Exception("Cidadão não encontrado no Keycloak")
