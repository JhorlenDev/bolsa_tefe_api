import uuid

from django.db import migrations, models
import django.db.models.deletion


def normalize_spaces(value):
    if value is None:
        return None
    value = ' '.join(str(value).split()).strip()
    return value or None


def normalize_localidade(value):
    value = normalize_spaces(value)
    return value.upper() if value else None


def normalize_rua(value):
    value = normalize_spaces(value)
    if not value:
        return None
    value = value.upper()
    replacements = {
        'AV. ': 'AVENIDA ',
        'AV ': 'AVENIDA ',
        'TRAV. ': 'TRAVESSA ',
        'TRAV ': 'TRAVESSA ',
        'TV. ': 'TRAVESSA ',
        'TV ': 'TRAVESSA ',
    }
    for prefix, replacement in replacements.items():
        if value.startswith(prefix):
            value = replacement + value[len(prefix):]
            break
    return ' '.join(value.split())


def seed_localidades_e_ruas(apps, schema_editor):
    LocalTefe = apps.get_model('api', 'LocalTefe')
    Localidade = apps.get_model('api', 'Localidade')
    Rua = apps.get_model('api', 'Rua')
    Endereco = apps.get_model('api', 'Endereco')

    tipo_map = {
        'BAIRRO': 'BAIRRO',
        'DISTRITO': 'DISTRITO',
        'COMUNIDADE': 'COMUNIDADE',
    }

    for item in LocalTefe.objects.all().iterator():
        nome = normalize_localidade(item.nome)
        tipo = tipo_map.get(item.tipo)
        if not nome or not tipo:
            continue
        Localidade.objects.get_or_create(
            nome=nome,
            defaults={
                'tipo': tipo,
                'criada_automaticamente': False,
                'sincronizado': True,
                'status_sincronizacao': 'SINCRONIZADO',
            },
        )

    for endereco in Endereco.objects.all().iterator():
        candidatos = []
        if getattr(endereco, 'bairro', ''):
            candidatos.append(('BAIRRO', endereco.bairro))
        if getattr(endereco, 'distrito', None):
            candidatos.append(('DISTRITO', endereco.distrito))
        if getattr(endereco, 'comunidade_localidade', None):
            candidatos.append(('COMUNIDADE', endereco.comunidade_localidade))

        localidade = None
        for tipo, nome_bruto in candidatos:
            nome = normalize_localidade(nome_bruto)
            if not nome:
                continue
            localidade, _ = Localidade.objects.get_or_create(
                nome=nome,
                defaults={
                    'tipo': tipo,
                    'criada_automaticamente': True,
                    'sincronizado': True,
                    'status_sincronizacao': 'SINCRONIZADO',
                },
            )
            break

        nome_rua = normalize_rua(getattr(endereco, 'logradouro', None))
        if localidade and nome_rua:
            Rua.objects.get_or_create(
                localidade=localidade,
                nome=nome_rua,
                defaults={
                    'criada_automaticamente': True,
                    'sincronizado': True,
                    'status_sincronizacao': 'SINCRONIZADO',
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0015_locaistefe'),
    ]

    operations = [
        migrations.CreateModel(
            name='Localidade',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('sincronizado', models.BooleanField(default=False)),
                ('status_sincronizacao', models.CharField(choices=[('PENDENTE', 'Pendente'), ('SINCRONIZADO', 'Sincronizado'), ('ERRO', 'Erro')], default='PENDENTE', max_length=20)),
                ('sincronizado_em', models.DateTimeField(blank=True, null=True)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('nome', models.CharField(max_length=200, unique=True)),
                ('tipo', models.CharField(choices=[('BAIRRO', 'Bairro'), ('COMUNIDADE', 'Comunidade'), ('DISTRITO', 'Distrito')], max_length=20)),
                ('criada_automaticamente', models.BooleanField(default=False)),
            ],
            options={
                'db_table': 'api_localidades',
                'ordering': ['nome'],
            },
        ),
        migrations.CreateModel(
            name='Rua',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('sincronizado', models.BooleanField(default=False)),
                ('status_sincronizacao', models.CharField(choices=[('PENDENTE', 'Pendente'), ('SINCRONIZADO', 'Sincronizado'), ('ERRO', 'Erro')], default='PENDENTE', max_length=20)),
                ('sincronizado_em', models.DateTimeField(blank=True, null=True)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('nome', models.CharField(max_length=200)),
                ('criada_automaticamente', models.BooleanField(default=False)),
                ('localidade', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ruas', to='api.localidade')),
            ],
            options={
                'db_table': 'api_ruas',
                'ordering': ['nome'],
            },
        ),
        migrations.AddConstraint(
            model_name='rua',
            constraint=models.UniqueConstraint(fields=('localidade', 'nome'), name='uq_rua_localidade_nome'),
        ),
        migrations.RunPython(seed_localidades_e_ruas, migrations.RunPython.noop),
    ]
