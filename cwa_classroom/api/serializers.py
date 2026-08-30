"""Identity serializers: who the caller is, and the login exchange."""

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer as BaseTokenObtainPairSerializer,
)

from accounts.models import CustomUser, Role


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ('name', 'display_name')


class UserSerializer(serializers.ModelSerializer):
    """The caller's own profile — what ``/api/v1/auth/me/`` returns.

    Deliberately narrow. This is the whole user row minus everything the app
    has no business holding on a device: the password hash, the block reason
    and blocking admin, the Stripe ids hanging off the subscription.
    """

    roles = serializers.SerializerMethodField()
    primary_role = serializers.CharField(read_only=True)
    full_name = serializers.SerializerMethodField()
    school = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name', 'full_name',
            'date_of_birth', 'phone', 'country', 'region', 'city',
            'street_address', 'postal_code',
            'roles', 'primary_role', 'school',
            'profile_completed', 'must_change_password', 'date_joined',
        )
        read_only_fields = (
            'id', 'username', 'roles', 'primary_role', 'school',
            'profile_completed', 'must_change_password', 'date_joined',
        )

    def get_full_name(self, obj) -> str:
        return obj.get_full_name() or obj.username

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_roles(self, obj):
        return list(
            obj.roles.filter(is_active=True).values_list('name', flat=True)
        )

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_school(self, obj):
        """The user's primary school, resolved the same way the web app does."""
        from billing.entitlements import get_school_for_user

        school = get_school_for_user(obj)
        if school is None:
            return None
        return {'id': school.id, 'name': school.name}


class UserSummarySerializer(serializers.ModelSerializer):
    """A person referenced from someone else's row (a teacher on a class, a
    student on a submission). Never carries contact details — those belong to
    the person, not to everyone who can see a row mentioning them."""

    full_name = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ('id', 'username', 'first_name', 'last_name', 'full_name')

    def get_full_name(self, obj) -> str:
        return obj.get_full_name() or obj.username


class TokenObtainPairSerializer(BaseTokenObtainPairSerializer):
    """Login. Adds role claims, and refuses a blocked account outright.

    The account-standing middlewares cannot help here: at login the caller is
    still anonymous, so they pass the request straight through. A blocked
    account that received a working token and only discovered the block on its
    next call would have been told it logged in successfully — so the block is
    checked once, here, at the only point where it is invisible to the
    middleware.

    Subscription and profile states are deliberately NOT re-checked: login
    succeeds and the very next call hits the middleware, which answers with
    the precise coded 403 for that state. Duplicating that cascade is how the
    two copies drift.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Claims the app can read without a round-trip. Kept to identity only:
        # anything that can change mid-session (a revoked role) must not be
        # trusted from the token, and the server re-checks roles per request.
        token['username'] = user.username
        token['primary_role'] = user.primary_role or ''
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user

        if user.is_blocked:
            # Mirrors AccountBlockMiddleware's auto-unblock: a temporary block
            # whose expiry has passed is not a block any more.
            expired = (
                user.block_type == 'temporary'
                and user.block_expires_at
                and user.block_expires_at <= timezone.now()
            )
            if expired:
                user.is_blocked = False
                user.block_type = ''
                user.block_expires_at = None
                user.save(update_fields=['is_blocked', 'block_type', 'block_expires_at'])
            else:
                raise serializers.ValidationError(
                    {'detail': 'This account has been blocked. '
                               'Contact your school administrator.'},
                    code='account_blocked',
                )

        data['user'] = UserSerializer(user, context=self.context).data
        return data
