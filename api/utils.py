from django.contrib.auth import get_user_model
from django.utils import timezone
from .models import KeycloakUserData

User = get_user_model()


def sync_user_keycloak(payload):
    keycloak_id = payload.get("sub")
    username = payload.get("preferred_username") or keycloak_id
    email = payload.get("email", "")
    first_name = payload.get("given_name", "")
    last_name = payload.get("family_name", "")
    roles = payload.get("realm_access", {}).get("roles", [])

    user, _ = User.objects.update_or_create(
        username=keycloak_id,
        defaults={
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "is_active": True,
        }
    )

    KeycloakUserData.objects.update_or_create(
        user=user,
        defaults={
            "keycloak_username": username,
            "roles": roles,
        }
    )

    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])

    return user