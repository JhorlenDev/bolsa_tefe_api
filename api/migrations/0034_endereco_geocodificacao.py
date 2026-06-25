from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0033_add_desatualizado_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='endereco',
            name='latitude',
            field=models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='endereco',
            name='longitude',
            field=models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='endereco',
            name='endereco_geocodificado',
            field=models.CharField(blank=True, default='', max_length=300),
        ),
        migrations.AddField(
            model_name='endereco',
            name='geocodificacao_status',
            field=models.CharField(
                choices=[
                    ('PENDENTE', 'Pendente'),
                    ('OK', 'Geocodificado'),
                    ('NAO_ENCONTRADO', 'Não encontrado'),
                    ('ERRO', 'Erro'),
                ],
                db_index=True,
                default='PENDENTE',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='endereco',
            name='geocodificacao_erro',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='endereco',
            name='geocodificado_em',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='endereco',
            name='precisao_geocodificacao',
            field=models.CharField(
                blank=True,
                choices=[
                    ('ENDERECO_EXATO', 'Endereço exato'),
                    ('RUA', 'Rua'),
                    ('LOCALIDADE', 'Localidade'),
                    ('MANUAL', 'Manual'),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='endereco',
            name='endereco_hash',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
