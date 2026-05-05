from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0016_localidade_rua'),
    ]

    operations = [
        migrations.AlterField(
            model_name='endereco',
            name='cep',
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
        migrations.AlterField(
            model_name='endereco',
            name='material_parede',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AlterField(
            model_name='endereco',
            name='numero',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AlterField(
            model_name='endereco',
            name='possui_asfalto',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='endereco',
            name='possui_lixo',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='endereco',
            name='possui_luz',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='endereco',
            name='possui_saneamento',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='endereco',
            name='qtd_comodos',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='endereco',
            name='situacao_imovel',
            field=models.CharField(blank=True, choices=[('PROPRIA', 'Própria'), ('ALUGADA', 'Alugada'), ('CEDIDA', 'Cedida'), ('TEMPORARIA', 'Temporária')], max_length=20, null=True),
        ),
    ]
