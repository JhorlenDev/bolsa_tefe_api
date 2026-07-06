from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0035_localidadebeneficiario'),
    ]

    operations = [
        migrations.AddField(
            model_name='socioeconomico',
            name='faixa_renda',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
    ]
