import logging
import re
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.cache import cache


logger = logging.getLogger(__name__)
_SESSION = requests.Session()
_OPERADOR_ROLE_NAME = 'USER-BOLSA-TEFE'
_TOKEN_CACHE_KEY = 'keycloak_admin_access_token'


class KeycloakAdminError(Exception):
    pass


class KeycloakAdminInputError(KeycloakAdminError):
    pass


class KeycloakAdminNotFoundError(KeycloakAdminError):
    pass


class KeycloakAdminPermissionError(KeycloakAdminError):
    pass


def _apenas_numeros(valor):
    return re.sub(r'\D', '', str(valor or ''))


def _normalizar_texto(valor):
    return str(valor or '').strip()


def _normalizar_email(valor):
    return _normalizar_texto(valor).lower()


def _admin_base_url():
    return f'{settings.KEYCLOAK_SERVER_URL}/admin/realms/{settings.KEYCLOAK_REALM}'


def _admin_headers(token):
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }


def _admin_token_url():
    return (
        f'{settings.KEYCLOAK_ISSUER}/protocol/openid-connect/token'
        if getattr(settings, 'KEYCLOAK_ISSUER', None)
        else getattr(settings, 'TEFE_TOKEN_URL', '')
    )


def _admin_client_credentials():
    client_id = _normalizar_texto(getattr(settings, 'KEYCLOAK_CLIENT_ID', ''))
    client_secret = _normalizar_texto(getattr(settings, 'KEYCLOAK_CLIENT_SECRET', ''))

    if not client_id or not client_secret:
        raise KeycloakAdminError(
            'Credenciais administrativas do Keycloak não configuradas. '
            'Verifique KEYCLOAK_CLIENT_ID e KEYCLOAK_CLIENT_SECRET.'
        )

    return client_id, client_secret


def _safe_body(text, limit=600):
    value = _normalizar_texto(text)
    if len(value) > limit:
        return value[:limit] + '...'
    return value


def _request_admin(method, url, **kwargs):
    response = _SESSION.request(
        method,
        url,
        timeout=settings.TEFE_HTTP_TIMEOUT,
        **kwargs,
    )

    if response.status_code == 403:
        logger.error(
            'keycloak_admin.forbidden method=%s url=%s status=%s body=%s',
            method,
            url,
            response.status_code,
            _safe_body(response.text),
        )
        raise KeycloakAdminPermissionError(
            'O Keycloak recusou o acesso administrativo. '
            'Verifique se o service account do client possui permissões no realm-management '
            '(realm-admin, manage-users, query-users, view-users, manage-realm).'
        )

    return response


def _obter_token_admin():
    client_id, client_secret = _admin_client_credentials()
    cache_key = f'{_TOKEN_CACHE_KEY}:{client_id}'

    cached_token = cache.get(cache_key)
    if cached_token:
        return cached_token

    response = _SESSION.post(
        _admin_token_url(),
        data={
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'client_credentials',
        },
        headers={
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        timeout=settings.TEFE_HTTP_TIMEOUT,
    )

    if response.status_code == 403:
        logger.error(
            'keycloak_admin.token_forbidden url=%s client_id=%s body=%s',
            _admin_token_url(),
            client_id,
            _safe_body(response.text),
        )
        raise KeycloakAdminPermissionError(
            'O client administrativo do Keycloak não tem permissão para autenticar. '
            'Verifique client authentication, service accounts roles e as permissões realm-management.'
        )

    response.raise_for_status()

    data = response.json()
    access_token = data.get('access_token')
    if not access_token:
        raise KeycloakAdminError('access_token não encontrado na resposta do Keycloak.')

    expires_in = int(data.get('expires_in') or settings.TEFE_TOKEN_CACHE_TIMEOUT)
    cache_timeout = max(1, min(expires_in - 30, settings.TEFE_TOKEN_CACHE_TIMEOUT))
    cache.set(cache_key, access_token, cache_timeout)

    return access_token


def _buscar_usuarios(token, params):
    response = _request_admin(
        'GET',
        f'{_admin_base_url()}/users',
        headers=_admin_headers(token),
        params=params,
    )

    if response.status_code in (400, 404):
        return []

    response.raise_for_status()
    body = response.json()
    if isinstance(body, list):
        return body
    return []


def _deduplicar_usuarios(usuarios):
    vistos = set()
    resultado = []
    for usuario in usuarios:
        usuario_id = str(usuario.get('id') or '').strip()
        if not usuario_id or usuario_id in vistos:
            continue
        vistos.add(usuario_id)
        resultado.append(usuario)
    return resultado


def _cpf_usuario(usuario):
    cpf_candidatos = []
    username = _apenas_numeros(usuario.get('username'))
    if len(username) == 11:
        cpf_candidatos.append(username)

    email = _apenas_numeros(usuario.get('email'))
    if len(email) == 11:
        cpf_candidatos.append(email)

    atributos = usuario.get('attributes') or {}
    for value in atributos.get('cpf', []) or []:
        cpf = _apenas_numeros(value)
        if len(cpf) == 11:
            cpf_candidatos.append(cpf)

    return cpf_candidatos


def _email_usuario(usuario):
    return _normalizar_email(usuario.get('email'))


def _buscar_usuario_por_cpf(token, cpf):
    cpf = _apenas_numeros(cpf)
    if not cpf:
        return None

    consultas = [
        {'username': cpf, 'exact': 'true'},
        {'search': cpf},
        {'q': f'cpf:{cpf}'},
    ]

    candidatos = []
    for params in consultas:
        candidatos.extend(_buscar_usuarios(token, params))

    for usuario in _deduplicar_usuarios(candidatos):
        if cpf in _cpf_usuario(usuario):
            return usuario

    return None


def _buscar_usuario_por_email(token, email):
    email = _normalizar_email(email)
    if not email:
        return None

    consultas = [
        {'email': email, 'exact': 'true'},
        {'search': email},
    ]

    candidatos = []
    for params in consultas:
        candidatos.extend(_buscar_usuarios(token, params))

    for usuario in _deduplicar_usuarios(candidatos):
        if _email_usuario(usuario) == email:
            return usuario

    return None


def _obter_role_realm(token, role_name):
    response = _request_admin(
        'GET',
        f'{_admin_base_url()}/roles/{quote(role_name, safe="")}',
        headers=_admin_headers(token),
    )

    if response.status_code == 404:
        return None

    response.raise_for_status()
    body = response.json()
    if isinstance(body, dict):
        return body
    return None


def _listar_roles_usuario(token, user_id):
    response = _request_admin(
        'GET',
        f'{_admin_base_url()}/users/{user_id}/role-mappings/realm',
        headers=_admin_headers(token),
    )

    response.raise_for_status()
    body = response.json()
    if isinstance(body, list):
        return body
    return []


def _adicionar_role_usuario(token, user_id, role):
    response = _request_admin(
        'POST',
        f'{_admin_base_url()}/users/{user_id}/role-mappings/realm',
        headers=_admin_headers(token),
        json=[role],
    )
    response.raise_for_status()


def _remover_role_usuario(token, user_id, role):
    response = _request_admin(
        'DELETE',
        f'{_admin_base_url()}/users/{user_id}/role-mappings/realm',
        headers=_admin_headers(token),
        json=[role],
    )
    response.raise_for_status()


def _serializar_usuario(usuario, cpf=None):
    atributos = usuario.get('attributes') or {}
    cpf_values = atributos.get('cpf') or []
    cpf_attr = ''
    for value in cpf_values:
        digits = _apenas_numeros(value)
        if digits:
            cpf_attr = digits
            break

    if not cpf_attr and cpf:
        cpf_attr = _apenas_numeros(cpf)

    return {
        'id': usuario.get('id'),
        'username': usuario.get('username') or usuario.get('preferredUsername') or '',
        'email': _normalizar_email(usuario.get('email')),
        'first_name': _normalizar_texto(usuario.get('firstName') or usuario.get('first_name')),
        'last_name': _normalizar_texto(usuario.get('lastName') or usuario.get('last_name')),
        'cpf': cpf_attr,
    }


def _localizar_usuario(token, cpf_normalizado, email_normalizado):
    """Localiza um único usuário priorizando o CPF e caindo para o e-mail."""
    usuario = None
    origem_busca = None

    if cpf_normalizado:
        usuario = _buscar_usuario_por_cpf(token, cpf_normalizado)
        origem_busca = 'cpf'

    if usuario is None and email_normalizado:
        usuario = _buscar_usuario_por_email(token, email_normalizado)
        origem_busca = 'email'

    return usuario, origem_busca


def _usuario_tem_role_operador(token, user_id):
    roles_atuais = _listar_roles_usuario(token, user_id)
    return any(
        (item or {}).get('name') == _OPERADOR_ROLE_NAME for item in roles_atuais
    )


def buscar_usuario_operador(cpf=None, email=None):
    """Busca um usuário no Keycloak e informa se já possui a role de operador."""
    cpf_normalizado = _apenas_numeros(cpf)
    email_normalizado = _normalizar_email(email)

    if not cpf_normalizado and not email_normalizado:
        raise KeycloakAdminInputError('Informe o CPF ou o e-mail do usuário.')

    token = _obter_token_admin()
    usuario, origem_busca = _localizar_usuario(token, cpf_normalizado, email_normalizado)

    if usuario is None:
        raise KeycloakAdminNotFoundError('Usuário não encontrado no Keycloak.')

    is_operador = _usuario_tem_role_operador(token, usuario['id'])
    logger.info(
        'keycloak_admin.operador_consultado origem=%s user_id=%s is_operador=%s',
        origem_busca,
        usuario.get('id'),
        is_operador,
    )

    return {
        'usuario': _serializar_usuario(usuario, cpf=cpf_normalizado),
        'is_operador': is_operador,
    }


def liberar_operador(cpf=None, email=None):
    cpf_normalizado = _apenas_numeros(cpf)
    email_normalizado = _normalizar_email(email)

    if not cpf_normalizado and not email_normalizado:
        raise KeycloakAdminInputError('Informe o CPF ou o e-mail do usuário.')

    token = _obter_token_admin()
    usuario, origem_busca = _localizar_usuario(token, cpf_normalizado, email_normalizado)

    if usuario is None:
        raise KeycloakAdminNotFoundError('Usuário não encontrado no Keycloak.')

    role = _obter_role_realm(token, _OPERADOR_ROLE_NAME)
    if role is None:
        raise KeycloakAdminNotFoundError(
            f'Role {_OPERADOR_ROLE_NAME} não encontrada no Keycloak.'
        )

    if _usuario_tem_role_operador(token, usuario['id']):
        logger.info(
            'keycloak_admin.operador_ja_liberado origem=%s user_id=%s username=%s',
            origem_busca,
            usuario.get('id'),
            usuario.get('username') or '',
        )
        return {
            'detail': 'O usuário já possui a role de operador.',
            'role_adicionada': False,
            'role_ja_existia': True,
            'usuario': _serializar_usuario(usuario, cpf=cpf_normalizado),
        }

    _adicionar_role_usuario(token, usuario['id'], role)
    logger.info(
        'keycloak_admin.operador_liberado origem=%s user_id=%s username=%s',
        origem_busca,
        usuario.get('id'),
        usuario.get('username') or '',
    )

    return {
        'detail': 'Operador liberado com sucesso.',
        'role_adicionada': True,
        'role_ja_existia': False,
        'usuario': _serializar_usuario(usuario, cpf=cpf_normalizado),
    }


def remover_operador(cpf=None, email=None):
    cpf_normalizado = _apenas_numeros(cpf)
    email_normalizado = _normalizar_email(email)

    if not cpf_normalizado and not email_normalizado:
        raise KeycloakAdminInputError('Informe o CPF ou o e-mail do usuário.')

    token = _obter_token_admin()
    usuario, origem_busca = _localizar_usuario(token, cpf_normalizado, email_normalizado)

    if usuario is None:
        raise KeycloakAdminNotFoundError('Usuário não encontrado no Keycloak.')

    role = _obter_role_realm(token, _OPERADOR_ROLE_NAME)
    if role is None:
        raise KeycloakAdminNotFoundError(
            f'Role {_OPERADOR_ROLE_NAME} não encontrada no Keycloak.'
        )

    if not _usuario_tem_role_operador(token, usuario['id']):
        logger.info(
            'keycloak_admin.operador_ja_removido origem=%s user_id=%s username=%s',
            origem_busca,
            usuario.get('id'),
            usuario.get('username') or '',
        )
        return {
            'detail': 'O usuário não possui a role de operador.',
            'role_removida': False,
            'role_ja_ausente': True,
            'usuario': _serializar_usuario(usuario, cpf=cpf_normalizado),
        }

    _remover_role_usuario(token, usuario['id'], role)
    logger.info(
        'keycloak_admin.operador_removido origem=%s user_id=%s username=%s',
        origem_busca,
        usuario.get('id'),
        usuario.get('username') or '',
    )

    return {
        'detail': 'Acesso de operador removido com sucesso.',
        'role_removida': True,
        'role_ja_ausente': False,
        'usuario': _serializar_usuario(usuario, cpf=cpf_normalizado),
    }
