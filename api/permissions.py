import logging

from rest_framework.permissions import BasePermission


logger = logging.getLogger(__name__)


class HasRequiredRole(BasePermission):
    def has_permission(self, request, view):
        required_role = getattr(view, 'required_role', None)

        if not required_role:
            logger.info(
                'permission.sem_role_obrigatoria path=%s method=%s view=%s',
                request.path,
                request.method,
                view.__class__.__name__,
            )
            return True

        roles = []
        roles_source = 'none'

        if getattr(request, 'user', None) and getattr(request.user, 'is_authenticated', False):
            keycloak_data = getattr(request.user, 'keycloak_data', None)
            if keycloak_data:
                roles = keycloak_data.roles or []
                roles_source = 'user.keycloak_data'

        if not roles:
            roles = getattr(request, 'jwt_roles', [])
            roles_source = 'request.jwt_roles' if roles else roles_source

        allowed = required_role in roles or 'USER-BOLSA-TEFE-ADMIN' in roles
        log_data = {
            'path': request.path,
            'method': request.method,
            'view': view.__class__.__name__,
            'required_role': required_role,
            'roles_source': roles_source,
            'roles': sorted(set(roles)),
            'user_is_authenticated': bool(
                getattr(getattr(request, 'user', None), 'is_authenticated', False)
            ),
            'user_id': getattr(getattr(request, 'user', None), 'id', None),
        }

        if allowed:
            logger.info('permission.ok %s', log_data)
        else:
            logger.warning('permission.negada %s', log_data)

        return allowed
