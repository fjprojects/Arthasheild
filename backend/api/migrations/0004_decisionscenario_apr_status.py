"""
Makes the persisted effective annual borrowing cost unambiguous.

Schema changes
---------------
* ``DecisionScenario.true_effective_apr`` becomes nullable, so "no reliable
  value" can be stored as NULL instead of being flattened to 0.0.
* ``DecisionScenario.apr_status`` records WHY a row has (or has not) a value:
  ``OK``, ``NOT_APPLICABLE``, ``UNAVAILABLE`` and the two legacy markers below.

Data backfill
-------------
Rows written before Task 18 carry no status and cannot be trusted as XIRR
results:

* A row with a non-zero APR was produced by the superseded fee-load formula.
  It is kept (it is what was actually recorded at the time) but explicitly
  marked ``LEGACY_SUPERSEDED`` so it is never read as a cash-flow result.
* A row storing ``0.0`` is ambiguous: it may be a genuine zero-cost loan, a
  zero-principal scenario, or the old "unavailable" fallback that stored 0.0.
  The value is cleared and the row is marked ``LEGACY_AMBIGUOUS_ZERO`` so a
  historic 0.0 is never presented as a genuine 0% result.
"""
from django.db import migrations, models


def backfill_legacy_apr_status(apps, schema_editor):
    """Label pre-existing rows so no legacy value masquerades as an XIRR result."""
    model = apps.get_model('api', 'DecisionScenario')

    # Values produced by the superseded fee-load formula: keep the number,
    # mark it as legacy.
    model.objects.filter(
        true_effective_apr__isnull=False,
    ).exclude(true_effective_apr=0).update(apr_status='LEGACY_SUPERSEDED')

    # Historic 0.0 values: genuinely ambiguous. Clear them rather than let a
    # consumer read 0.0 as a verified zero-cost loan.
    model.objects.filter(true_effective_apr=0).update(
        true_effective_apr=None,
        apr_status='LEGACY_AMBIGUOUS_ZERO',
    )


def restore_legacy_zero_values(apps, schema_editor):
    """Reverse helper: put 0.0 back so the NOT NULL column can be restored."""
    model = apps.get_model('api', 'DecisionScenario')
    model.objects.filter(true_effective_apr__isnull=True).update(true_effective_apr=0.0)


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0003_securesession'),
    ]

    operations = [
        migrations.AddField(
            model_name='decisionscenario',
            name='apr_status',
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.AlterField(
            model_name='decisionscenario',
            name='true_effective_apr',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_legacy_apr_status, restore_legacy_zero_values),
    ]
