from django.db import migrations


def corrigir_datas_invalidas(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE api_cidadao
            SET data_nascimento = NULL
            WHERE data_nascimento IS NOT NULL
              AND (
                data_nascimento::text ~ '^[0-9]{5,}'
                OR substring(data_nascimento::text from 1 for 4)::int < 1900
                OR substring(data_nascimento::text from 1 for 4)::int > 2100
              )
            """
        )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0017_endereco_importacao_flexivel'),
    ]

    operations = [
        migrations.RunPython(corrigir_datas_invalidas, migrations.RunPython.noop),
    ]
