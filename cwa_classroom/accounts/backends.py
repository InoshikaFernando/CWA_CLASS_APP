from django.contrib.auth.backends import ModelBackend
from .models import CustomUser


class EmailOrUsernameBackend(ModelBackend):
    """Allow login with either username or email address."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        # Try username first (default behavior)
        user = None
        try:
            user = CustomUser.objects.get(username=username)
        except CustomUser.DoesNotExist:
            # Try email lookup
            try:
                user = CustomUser.objects.get(email__iexact=username)
            except (CustomUser.DoesNotExist, CustomUser.MultipleObjectsReturned):
                return None

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
