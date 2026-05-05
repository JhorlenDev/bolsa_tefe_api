from django.db import migrations


def backfill_enderecos_rurais(apps, schema_editor):
    Endereco = apps.get_model('api', 'Endereco')
    Localidade = apps.get_model('api', 'Localidade')
    LocalTefe = apps.get_model('api', 'LocalTefe')

    for endereco in Endereco.objects.all().iterator():
        bairro = (endereco.bairro or '').strip()
        distrito = (endereco.distrito or '').strip()
        comunidade = (endereco.comunidade_localidade or '').strip()
        tipo_localizacao = (endereco.tipo_localizacao or '').strip().upper()

        if tipo_localizacao == 'RURAL':
            tipo_localizacao = 'RURAL_DISTRITO'

        if not bairro and not distrito and not comunidade:
            continue

        localidade_tipo = None
        localidade_nome = None

        if bairro:
            localidade = Localidade.objects.filter(nome__iexact=bairro).first()
            if localidade:
                localidade_tipo = localidade.tipo
                localidade_nome = localidade.nome
            else:
                local_tefe = LocalTefe.objects.filter(nome__iexact=bairro).first()
                if local_tefe:
                    localidade_tipo = local_tefe.tipo
                    localidade_nome = local_tefe.nome

        update_fields = []

        if tipo_localizacao != 'RURAL_DISTRITO' and (
            distrito or comunidade or localidade_tipo in {'DISTRITO', 'COMUNIDADE'}
        ):
            endereco.tipo_localizacao = 'RURAL_DISTRITO'
            update_fields.append('tipo_localizacao')

        if endereco.tipo_localizacao == 'RURAL_DISTRITO':
            if localidade_tipo == 'DISTRITO' and not distrito:
                endereco.distrito = localidade_nome
                update_fields.append('distrito')
            if localidade_tipo == 'COMUNIDADE' and not comunidade:
                endereco.comunidade_localidade = localidade_nome
                update_fields.append('comunidade_localidade')
            if bairro:
                endereco.bairro = ''
                update_fields.append('bairro')

        if update_fields:
            endereco.save(update_fields=list(dict.fromkeys(update_fields)))


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0018_corrige_datas_invalidas_cidadao'),
    ]

    operations = [
        migrations.RunPython(backfill_enderecos_rurais, migrations.RunPython.noop),
    ]
