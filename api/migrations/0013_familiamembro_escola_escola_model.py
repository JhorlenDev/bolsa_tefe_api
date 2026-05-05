import uuid

from django.db import migrations, models


ESCOLAS_INICIAIS = [
    'Escola Municipal Walter Cabral',
    'Escola Municipal Santa Teresa',
    'Escola Municipal Wenceslau de Queiroz',
    'Escola Municipal Gilberto Mestrinho',
    'Escola Estadual Frei Andre da Costa',
]


def seed_escolas(apps, schema_editor):
    Escola = apps.get_model('api', 'Escola')
    for nome in ESCOLAS_INICIAIS:
        Escola.objects.get_or_create(
            nome=nome,
            defaults={
                'sincronizado': True,
                'status_sincronizacao': 'SINCRONIZADO',
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0012_endereco_tipo_localizacao'),
    ]

    operations = [
        migrations.AddField(
            model_name='familiamembro',
            name='escola_em_que_estuda',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.CreateModel(
            name='Escola',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('sincronizado', models.BooleanField(default=False)),
                ('status_sincronizacao', models.CharField(choices=[('PENDENTE', 'Pendente'), ('SINCRONIZADO', 'Sincronizado'), ('ERRO', 'Erro')], default='PENDENTE', max_length=20)),
                ('sincronizado_em', models.DateTimeField(blank=True, null=True)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('nome', models.CharField(max_length=200, unique=True)),
            ],
            options={
                'db_table': 'api_escola',
                'ordering': ['nome'],
            },
        ),
        migrations.RunPython(seed_escolas, migrations.RunPython.noop),
    ]
