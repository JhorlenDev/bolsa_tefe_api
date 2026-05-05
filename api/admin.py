from django.contrib import admin

from .models import (
    Beneficiario,
    Beneficio,
    Cidadao,
    Documento,
    DocumentoAnexo,
    Endereco,
    Escola,
    FamiliaMembro,
    KeycloakUserData,
    LocalTefe,
    Localidade,
    Rua,
    Socioeconomico,
)


@admin.register(KeycloakUserData)
class KeycloakUserDataAdmin(admin.ModelAdmin):
    list_display = ('user', 'keycloak_username')


@admin.register(Cidadao)
class CidadaoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome', 'telefone', 'data_nascimento', 'sincronizado')
    search_fields = ('nome', 'nis', 'documentos__cpf')
    list_filter = ('estado_civil', 'possui_deficiencia', 'status_sincronizacao')


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ('id', 'cidadao', 'cpf', 'rg', 'sincronizado')
    search_fields = ('cidadao__nome', 'cpf', 'rg')
    list_filter = ('status_sincronizacao', 'rg_uf')


@admin.register(DocumentoAnexo)
class DocumentoAnexoAdmin(admin.ModelAdmin):
    list_display = ('id', 'cidadao', 'tipo_documento', 'nome_arquivo', 'status')
    search_fields = ('cidadao__nome', 'nome_arquivo', 'tipo_documento')
    list_filter = ('tipo_documento', 'status')


@admin.register(Endereco)
class EnderecoAdmin(admin.ModelAdmin):
    list_display = (
        'cidadao',
        'tipo_localizacao',
        'logradouro',
        'numero',
        'bairro',
        'distrito',
        'cep',
    )
    search_fields = ('cidadao__nome', 'cep', 'bairro', 'distrito', 'comunidade_localidade')
    list_filter = ('tipo_localizacao',)


@admin.register(FamiliaMembro)
class FamiliaMembroAdmin(admin.ModelAdmin):
    list_display = ('id', 'cidadao_titular', 'nome_membro', 'parentesco')
    search_fields = ('cidadao_titular__nome', 'nome_membro', 'cpf_membro')
    list_filter = ('parentesco', 'possui_doenca_grave', 'uso_substancia_ilicita')


@admin.register(Escola)
class EscolaAdmin(admin.ModelAdmin):
    list_display = ('id', 'codigo', 'nome', 'tipo', 'zona')
    search_fields = ('codigo', 'nome', 'tipo', 'zona')
    list_filter = ('tipo', 'zona')


@admin.register(LocalTefe)
class LocalTefeAdmin(admin.ModelAdmin):
    list_display = ('id', 'tipo', 'nome', 'ativo', 'ordem')
    search_fields = ('nome', 'tipo')
    list_filter = ('tipo', 'ativo')


@admin.register(Localidade)
class LocalidadeAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome', 'tipo', 'criada_automaticamente')
    search_fields = ('nome', 'tipo')
    list_filter = ('tipo', 'criada_automaticamente')


@admin.register(Rua)
class RuaAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome', 'localidade', 'criada_automaticamente')
    search_fields = ('nome', 'localidade__nome')
    list_filter = ('criada_automaticamente', 'localidade__tipo')


@admin.register(Socioeconomico)
class SocioeconomicoAdmin(admin.ModelAdmin):
    list_display = ('id', 'cidadao', 'renda_total', 'utiliza_servico_social')
    search_fields = ('cidadao__nome',)
    list_filter = ('utiliza_servico_social', 'mais_de_um_nucleo')


@admin.register(Beneficio)
class BeneficioAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome', 'ativo')
    search_fields = ('nome',)
    list_filter = ('ativo',)


@admin.register(Beneficiario)
class BeneficiarioAdmin(admin.ModelAdmin):
    list_display = ('id', 'cidadao', 'beneficio', 'status')
    search_fields = ('cidadao__nome', 'beneficio__nome')
    list_filter = ('status', 'beneficio')
