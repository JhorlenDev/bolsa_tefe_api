from django.db import migrations, models


STATUS_CHOICES = [
    ('EM_ANALISE', 'Em análise'),
    ('APROVADO', 'Aprovado'),
    ('REPROVADO', 'Reprovado'),
]


def ensure_situacao_cadastro(apps, schema_editor):
    table_name = 'api_beneficiario'
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in connection.introspection.get_table_description(
                cursor,
                table_name,
            )
        }

    if 'situacao_cadastro' not in existing_columns:
        Beneficiario = apps.get_model('api', 'Beneficiario')
        field = models.CharField(
            max_length=20,
            choices=STATUS_CHOICES,
            default='EM_ANALISE',
            db_index=True,
        )
        field.set_attributes_from_name('situacao_cadastro')
        schema_editor.add_field(Beneficiario, field)

    schema_editor.execute(
        """
        UPDATE api_beneficiario
        SET situacao_cadastro = COALESCE(situacao_cadastro, status, 'EM_ANALISE')
        """
    )

    if connection.vendor == 'postgresql':
        schema_editor.execute(
            """
            ALTER TABLE api_beneficiario
            ALTER COLUMN situacao_cadastro SET DEFAULT 'EM_ANALISE'
            """
        )
        schema_editor.execute(
            """
            ALTER TABLE api_beneficiario
            ALTER COLUMN situacao_cadastro SET NOT NULL
            """
        )
        schema_editor.execute(
            """
            CREATE INDEX IF NOT EXISTS api_beneficiario_situacao_cadastro_idx
            ON api_beneficiario (situacao_cadastro)
            """
        )


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0038_beneficio_icone'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    ensure_situacao_cadastro,
                    reverse_code=migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='beneficiario',
                    name='situacao_cadastro',
                    field=models.CharField(
                        choices=STATUS_CHOICES,
                        db_index=True,
                        default='EM_ANALISE',
                        max_length=20,
                    ),
                ),
            ],
        ),
    ]
