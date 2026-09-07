"""drf-spectacular extensions.

Without this, the custom authentication class is unknown to the generator and
the schema comes out with no security scheme at all — so a client generated
from it would never send the Authorization header and every call would 401.
"""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class WalledJWTAuthenticationExtension(OpenApiAuthenticationExtension):
    target_class = 'api.authentication.WalledJWTAuthentication'
    name = 'jwtAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT',
            'description': (
                'Access token from POST /api/v1/auth/login/. '
                'Send as: Authorization: Bearer <access token>.'
            ),
        }
