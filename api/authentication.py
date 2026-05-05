import logging

import jwt
import requests
from jwt import PyJWK
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.authentication import BaseAuthentication
from rest_framework import exceptions
from django.conf import settings

from .models import KeycloakUserData


logger = logging.getLogger(__name__)


def _mask(value, visible=6):
    if not value:
        return ''
    value = str(value)
    if len(value) <= visible * 2:
        return f'{value[:visible]}...'
    return f'{value[:visible]}...{value[-visible:]}'


class KeycloakJWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.headers.get('Authorization', '')

        if not auth_header:
            logger.info(
                'auth.sem_header path=%s method=%s',
                request.path,
                request.method,
            )
            return None

        parts = auth_header.split()

        if len(parts) != 2 or parts[0].lower() != 'bearer':
            logger.warning(
                'auth.header_invalido path=%s method=%s header_prefix=%s',
                request.path,
                request.method,
                _mask(auth_header, visible=12),
            )
            raise exceptions.AuthenticationFailed('Header Authorization inválido.')

        token = parts[1]

        try:
            signing_key = self._get_signing_key(token)

            payload = jwt.decode(
                token,
                signing_key,
                algorithms=['RS256'],
                issuer=settings.KEYCLOAK_ISSUER,
                options={
                    'verify_signature': True,
                    'verify_exp': True,
                    'verify_iss': True,
                    'verify_aud': False,
                },
            )

        except requests.RequestException as e:
            logger.exception(
                'auth.keycloak_conexao_erro path=%s method=%s erro=%s',
                request.path,
                request.method,
                str(e),
            )
            raise exceptions.AuthenticationFailed(
                f'Erro ao conectar no Keycloak: {str(e)}'
            )
        except jwt.ExpiredSignatureError:
            logger.warning(
                'auth.token_expirado path=%s method=%s',
                request.path,
                request.method,
            )
            raise exceptions.AuthenticationFailed('Token expirado.')
        except jwt.InvalidIssuerError:
            logger.warning(
                'auth.issuer_invalido path=%s method=%s issuer_esperado=%s',
                request.path,
                request.method,
                settings.KEYCLOAK_ISSUER,
            )
            raise exceptions.AuthenticationFailed('Issuer inválido.')
        except jwt.InvalidTokenError as e:
            logger.warning(
                'auth.token_invalido path=%s method=%s erro=%s',
                request.path,
                request.method,
                str(e),
            )
            raise exceptions.AuthenticationFailed(f'Token inválido: {str(e)}')
        except Exception as e:
            logger.exception(
                'auth.validacao_erro path=%s method=%s erro=%s',
                request.path,
                request.method,
                str(e),
            )
            raise exceptions.AuthenticationFailed(f'Erro ao validar token: {str(e)}')

        roles = self._extract_roles(payload)

        request.jwt_payload = payload
        request.jwt_roles = roles

        user = self._sync_user(payload, roles)
        logger.info(
            'auth.ok path=%s method=%s user_id=%s username=%s preferred_username=%s email=%s roles=%s',
            request.path,
            request.method,
            user.id,
            _mask(user.username),
            payload.get('preferred_username') or '',
            payload.get('email') or '',
            sorted(roles),
        )
        return (user, payload)

    def _get_signing_key(self, token):
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get('kid')

        if not kid:
            logger.warning('auth.token_sem_kid')
            raise exceptions.AuthenticationFailed('Token sem kid no header.')

        cache_key = f'keycloak_jwk:{kid}'
        cached_jwk = cache.get(cache_key)
        if cached_jwk:
            logger.info('auth.jwk_cache_hit kid=%s', _mask(kid))
            return PyJWK.from_dict(cached_jwk).key

        jwks = cache.get('keycloak_jwks')
        if jwks is None:
            logger.info(
                'auth.jwks_fetch url=%s timeout=%s',
                settings.KEYCLOAK_JWKS_URL,
                settings.TEFE_HTTP_TIMEOUT,
            )
            response = requests.get(
                settings.KEYCLOAK_JWKS_URL,
                timeout=settings.TEFE_HTTP_TIMEOUT,
            )
            response.raise_for_status()
            jwks = response.json()
            cache.set('keycloak_jwks', jwks, settings.KEYCLOAK_JWKS_CACHE_TIMEOUT)
        else:
            logger.info('auth.jwks_cache_hit')

        keys = jwks.get('keys', [])

        for jwk_dict in keys:
            if jwk_dict.get('kid') == kid:
                signing_key = PyJWK.from_dict(jwk_dict).key
                cache.set(
                    cache_key,
                    jwk_dict,
                    settings.KEYCLOAK_JWKS_CACHE_TIMEOUT,
                )
                return signing_key

        logger.warning('auth.jwk_nao_encontrada kid=%s total_keys=%s', _mask(kid), len(keys))
        raise exceptions.AuthenticationFailed('Chave pública não encontrada para o token.')

    def _extract_roles(self, payload):
        roles = set()

        realm_roles = payload.get('realm_access', {}).get('roles', [])
        roles.update(realm_roles)

        resource_access = payload.get('resource_access', {})
        for client_data in resource_access.values():
            client_roles = client_data.get('roles', [])
            roles.update(client_roles)

        return list(roles)

    def _sync_user(self, payload, roles):
        UserModel = get_user_model()
        keycloak_subject = payload.get('ksub') or payload.get('sub')

        if not keycloak_subject:
            logger.warning(
                'auth.token_sem_subject preferred_username=%s email=%s',
                payload.get('preferred_username') or '',
                payload.get('email') or '',
            )
            raise exceptions.AuthenticationFailed(
                'Token sem identificador único do usuário (ksub/sub).'
            )

        defaults = {
            'email': payload.get('email', '') or '',
            'first_name': payload.get('given_name', '') or '',
            'last_name': payload.get('family_name', '') or '',
            'is_active': True,
        }

        user, created = UserModel.objects.get_or_create(
            username=keycloak_subject,
            defaults=defaults,
        )

        updated_fields = []
        for field, value in defaults.items():
            if getattr(user, field) != value:
                setattr(user, field, value)
                updated_fields.append(field)

        if created:
            user.set_unusable_password()
            updated_fields.append('password')

        preferred_username = payload.get('preferred_username')
        user.jwt_payload = payload
        user.jwt_roles = roles

        if updated_fields:
            user.save(update_fields=updated_fields)

        keycloak_data_defaults = {
            'keycloak_username': preferred_username or '',
            'roles': sorted(set(roles)),
        }
        keycloak_data, keycloak_data_created = KeycloakUserData.objects.get_or_create(
            user=user,
            defaults=keycloak_data_defaults,
        )

        keycloak_data_updated_fields = []
        for field, value in keycloak_data_defaults.items():
            if getattr(keycloak_data, field) != value:
                setattr(keycloak_data, field, value)
                keycloak_data_updated_fields.append(field)

        if keycloak_data_created:
            keycloak_data_updated_fields = []

        if keycloak_data_updated_fields:
            keycloak_data.save(update_fields=keycloak_data_updated_fields)
        elif keycloak_data_created:
            keycloak_data.save()

        user.keycloak_data = keycloak_data
        logger.info(
            'auth.user_sync user_id=%s created=%s keycloak_data_created=%s preferred_username=%s roles=%s',
            user.id,
            created,
            keycloak_data_created,
            preferred_username or '',
            keycloak_data.roles,
        )
        return user
