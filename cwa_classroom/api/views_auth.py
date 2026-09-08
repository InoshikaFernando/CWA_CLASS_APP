"""Login, refresh, logout and the caller's own profile."""

from django.contrib.auth import update_session_auth_hash
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import (
    TokenObtainPairView as BaseTokenObtainPairView,
    TokenRefreshView as BaseTokenRefreshView,
    TokenVerifyView as BaseTokenVerifyView,
)

from api.serializers import TokenPairSerializer, UserSerializer


@extend_schema(responses={200: TokenPairSerializer})
class LoginView(BaseTokenObtainPairView):
    """POST username/email + password → access and refresh tokens.

    The username field accepts an email too: the project authenticates through
    ``accounts.backends.EmailOrUsernameBackend``, and a student who signs in to
    the website with their email would otherwise be told their password was
    wrong on the phone.
    """

    permission_classes = [AllowAny]
    throttle_scope = 'auth'
    # The serializer comes from SIMPLE_JWT['TOKEN_OBTAIN_SERIALIZER'], and it
    # builds its response in validate() rather than declaring output fields —
    # which drf-spectacular cannot introspect. Hence the explicit `responses`
    # above; without it the schema documented this as having no body at all.


class RefreshView(BaseTokenRefreshView):
    """Exchange a refresh token for a new access token.

    Rotation is on, so the response also carries a NEW refresh token and the
    one just used is blacklisted. The client must store the returned refresh
    token — replaying the old one will be rejected.
    """

    permission_classes = [AllowAny]
    throttle_scope = 'auth'


class VerifyView(BaseTokenVerifyView):
    """Cheap "is this token still good?" check for app start-up."""

    permission_classes = [AllowAny]
    throttle_scope = 'auth'


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(
        help_text='The refresh token to revoke.')


class LogoutView(APIView):
    """Revoke a refresh token.

    Without this, "log out" on a phone can only forget the tokens locally —
    a copy taken off the device would keep working until it expired, which
    with a 30-day refresh lifetime is a long time to be wrong about.

    The access token is not revoked (it is stateless and short-lived by
    design); the client discards it and it dies on its own.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = LogoutSerializer

    @extend_schema(
        request=LogoutSerializer,
        responses={205: OpenApiResponse(description='Refresh token revoked.')},
    )
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data['refresh']).blacklist()
        except TokenError as exc:
            # An already-revoked or malformed token is reported, not swallowed:
            # a client that thinks it logged out when it did not is exactly the
            # kind of silent failure this project bans.
            raise serializers.ValidationError(
                {'refresh': [f'Token could not be revoked: {exc}']})
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(APIView):
    """The signed-in user's own profile.

    GET returns it; PATCH updates the handful of fields a person owns about
    themselves. Roles, school membership and account standing are deliberately
    not writable — those are granted by a school, not chosen by the holder.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    @extend_schema(responses=UserSerializer)
    def get(self, request):
        return Response(UserSerializer(request.user, context={'request': request}).data)

    @extend_schema(request=UserSerializer, responses=UserSerializer)
    def patch(self, request):
        serializer = UserSerializer(
            request.user, data=request.data, partial=True,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_current_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect.')
        return value

    def validate_new_password(self, value):
        from django.contrib.auth.password_validation import validate_password
        # Run the project's configured validators rather than a length check of
        # our own, so the app enforces the same policy as the website.
        validate_password(value, self.context['request'].user)
        return value


class ChangePasswordView(APIView):
    """Change the caller's own password.

    Also clears ``must_change_password``, which is the flag that walls a
    newly-created account behind the profile gate — so a student created by a
    head of institute can complete that step from the app instead of being
    told to go and find a browser.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer
    throttle_scope = 'auth'

    @extend_schema(
        request=ChangePasswordSerializer,
        responses={200: OpenApiResponse(description='Password changed.')},
    )
    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        update_fields = ['password']
        if user.must_change_password:
            user.must_change_password = False
            update_fields.append('must_change_password')
        user.save(update_fields=update_fields)

        # Keep a browser session (if this came from the web client) alive —
        # Django cycles the session key on a password change.
        if request.session.session_key:
            update_session_auth_hash(request, user)

        revoked = _revoke_refresh_tokens(user)

        # Changing a password is how someone reacts to a device being lost or
        # a password being shared. If the old refresh tokens kept working, the
        # very thing the user did to lock an intruder out would leave them
        # thirty days of access.
        return Response({'detail': 'Password changed.',
                         'sessions_revoked': revoked})


def _revoke_refresh_tokens(user):
    """Blacklist every outstanding refresh token for *user*. Returns the count.

    Uses the token_blacklist app's own tables, which SimpleJWT already
    maintains for rotation, so this shares the machinery rotation uses rather
    than adding a parallel revocation list.
    """
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken, OutstandingToken,
    )

    revoked = 0
    for token in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        if created:
            revoked += 1
    return revoked
