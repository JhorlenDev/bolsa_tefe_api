from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0024_expand_documento_anexo_tipos'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='cidadao',
            index=models.Index(
                fields=['atualizado_em'],
                name='api_cidadao_atualizado_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='beneficiario',
            index=models.Index(
                fields=['atualizado_em'],
                name='api_benefic_atualiz_0102e4_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='beneficio',
            index=models.Index(
                fields=['atualizado_em'],
                name='api_beneficio_atualiz_idx',
            ),
        ),
    ]
