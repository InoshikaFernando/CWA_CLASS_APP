"""
Run with: python manage.py shell < update_free_trial.py

Sets trial_days=7 on all free (price=0) packages.
"""
from billing.models import Package

updated = Package.objects.filter(price=0).update(trial_days=7)
print(f"Updated {updated} free package(s) to trial_days=7")

# Show current state
for p in Package.objects.all().order_by('order'):
    print(f"  {p.name}: price=${p.price}, trial_days={p.trial_days}")
