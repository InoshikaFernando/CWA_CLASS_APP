"""Signal receivers for WhatsApp notifications.

Sprint 2 wires the homework events here: the homework app dispatches custom
signals (``homework_published``, ``submission_completed``) via ``send_robust``
so a receiver error can never break publishing/submission, and receivers below
call ``whatsapp.services.notify_*``. Intentionally empty until then.
"""
