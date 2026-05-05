import uuid

from django.db import migrations, models


SEED_LOCAIS_TEFE = [
    ('BAIRRO', 'Abial', 10),
    ('BAIRRO', 'Centro', 20),
    ('BAIRRO', 'Colonia Ventura', 30),
    ('BAIRRO', 'Juruá', 40),
    ('BAIRRO', 'Jerusalém', 50),
    ('BAIRRO', 'Mutirão', 60),
    ('BAIRRO', 'Nossa Senhora de Fátima', 70),
    ('BAIRRO', 'Santa Luzia', 80),
    ('BAIRRO', 'Sao Francisco', 90),
    ('BAIRRO', 'Sao Joao', 100),
    ('DISTRITO', 'Caiambé', 110),
    ('DISTRITO', 'Área Rural de Tefé', 120),
]


def seed_locais_tefe(apps, schema_editor):
    LocalTefe = apps.get_model('api', 'LocalTefe')
    for tipo, nome, ordem in SEED_LOCAIS_TEFE:
        LocalTefe.objects.get_or_create(
            tipo=tipo,
            nome=nome,
            defaults={
                'ativo': True,
                'ordem': ordem,
                'sincronizado': True,
                'status_sincronizacao': 'SINCRONIZADO',
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0014_documentoanexo_rg_frente_verso'),
    ]

    operations = [
        migrations.CreateModel(
            name='LocalTefe',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('sincronizado', models.BooleanField(default=False)),
                ('status_sincronizacao', models.CharField(choices=[('PENDENTE', 'Pendente'), ('SINCRONIZADO', 'Sincronizado'), ('ERRO', 'Erro')], default='PENDENTE', max_length=20)),
                ('sincronizado_em', models.DateTimeField(blank=True, null=True)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('tipo', models.CharField(choices=[('BAIRRO', 'Bairro'), ('DISTRITO', 'Distrito'), ('COMUNIDADE', 'Comunidade')], max_length=20)),
                ('nome', models.CharField(max_length=200)),
                ('ativo', models.BooleanField(default=True)),
                ('ordem', models.IntegerField(default=0)),
            ],
            options={
                'db_table': 'api_locais_tefe',
                'ordering': ['ordem', 'nome'],
            },
        ),
        migrations.AddConstraint(
            model_name='localtefe',
            constraint=models.UniqueConstraint(fields=('tipo', 'nome'), name='uq_local_tefe_tipo_nome'),
        ),
        migrations.RunPython(seed_locais_tefe, migrations.RunPython.noop),
    ]
