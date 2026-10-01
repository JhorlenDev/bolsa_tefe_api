from django.utils import timezone
from django.db import transaction
from django.conf import settings
from rest_framework import serializers
from decimal import Decimal, InvalidOperation
from pathlib import Path
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field

from .models import (
    Beneficiario,
    Beneficio,
    Cidadao,
    Documento,
    DocumentoAnexo,
    Endereco,
    Escola,
    FamiliaMembro,
    LocalTefe,
    Localidade,
    Rua,
    Socioeconomico,
    TermoResponsabilidade,
)


RURAL_BAIRROS_LEGADOS = {'Caiambé', 'Área Rural de Tefé'}
DOCUMENTO_TIPO_ALIASES = {
    DocumentoAnexo.TIPO_RG: DocumentoAnexo.TIPO_RG_FRENTE,
    DocumentoAnexo.TIPO_RG_FRENTE: DocumentoAnexo.TIPO_RG_FRENTE,
    DocumentoAnexo.TIPO_RG_VERSO: DocumentoAnexo.TIPO_RG_VERSO,
    DocumentoAnexo.TIPO_CPF: DocumentoAnexo.TIPO_CPF,
    DocumentoAnexo.TIPO_CERTIDAO_NASCIMENTO: DocumentoAnexo.TIPO_CERTIDAO_NASCIMENTO,
    DocumentoAnexo.TIPO_CERTIDAO_CASAMENTO: DocumentoAnexo.TIPO_CERTIDAO_CASAMENTO,
    DocumentoAnexo.TIPO_QUITACAO_ELEITORAL: DocumentoAnexo.TIPO_QUITACAO_ELEITORAL,
    'certidao_quitacao_eleitoral': DocumentoAnexo.TIPO_QUITACAO_ELEITORAL,
    DocumentoAnexo.TIPO_COMPROVANTE_RESIDENCIA: DocumentoAnexo.TIPO_COMPROVANTE_RESIDENCIA,
    DocumentoAnexo.TIPO_FOTO_RESIDENCIA: DocumentoAnexo.TIPO_FOTO_RESIDENCIA,
    DocumentoAnexo.TIPO_FOTO_ATO_ATUALIZACAO: DocumentoAnexo.TIPO_FOTO_ATO_ATUALIZACAO,
}


def _normalize_text(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


INVALID_ENDERECO_VALUES = {
    'CASA',
    'X',
    'NAO ANOTOU',
    'NAO INFORMADO',
    'NÃO ANOTOU',
    'NÃO INFORMADO',
}


def _resolve_rural_localidade_from_catalog(nome):
    nome_normalizado = _normalize_text(nome)
    if nome_normalizado is None:
        return (None, None)

    localidade = Localidade.objects.filter(nome__iexact=nome_normalizado).first()
    if localidade:
        return (localidade.tipo, localidade.nome)

    local_tefe = LocalTefe.objects.filter(nome__iexact=nome_normalizado).first()
    if local_tefe:
        return (local_tefe.tipo, local_tefe.nome)

    return (None, None)


def _normalize_tipo_localizacao(value):
    tipo = _normalize_text(value)
    if tipo is None:
        return None
    tipo = tipo.upper()
    if tipo == 'RURAL':
        return 'RURAL_DISTRITO'
    return tipo


def _endereco_is_rural_from_values(tipo_localizacao, bairro, distrito, comunidade_localidade=None):
    tipo = _normalize_tipo_localizacao(tipo_localizacao)
    bairro_normalizado = _normalize_text(bairro)
    distrito_normalizado = _normalize_text(distrito)
    comunidade_normalizada = _normalize_text(comunidade_localidade)
    catalog_tipo, _ = _resolve_rural_localidade_from_catalog(bairro_normalizado)
    return (
        tipo == 'RURAL_DISTRITO'
        or bairro_normalizado in RURAL_BAIRROS_LEGADOS
        or distrito_normalizado is not None
        or comunidade_normalizada is not None
        or catalog_tipo in {'DISTRITO', 'COMUNIDADE'}
    )


def normalize_endereco_payload(payload, instance=None):
    if payload is None:
        return None

    normalized = dict(payload)
    current = instance

    tipo_localizacao = _normalize_tipo_localizacao(
        normalized.get(
            'tipo_localizacao',
            getattr(current, 'tipo_localizacao', None),
        )
    )
    bairro = _normalize_text(normalized.get('bairro', getattr(current, 'bairro', None)))
    distrito = _normalize_text(
        normalized.get('distrito', getattr(current, 'distrito', None))
    )
    comunidade_localidade = _normalize_text(
        normalized.get(
            'comunidade_localidade',
            getattr(current, 'comunidade_localidade', None),
        )
    )
    qtd_comodos = normalized.get('qtd_comodos', getattr(current, 'qtd_comodos', None))
    if qtd_comodos in (None, ''):
        normalized['qtd_comodos'] = 1
    else:
        try:
            qtd_comodos_int = int(qtd_comodos)
        except (TypeError, ValueError):
            qtd_comodos_int = 1
        normalized['qtd_comodos'] = max(qtd_comodos_int, 1)

    is_rural = _endereco_is_rural_from_values(
        tipo_localizacao,
        bairro,
        distrito,
        comunidade_localidade,
    )

    if tipo_localizacao is None:
        tipo_localizacao = 'RURAL_DISTRITO' if is_rural else 'URBANO'

    normalized['tipo_localizacao'] = tipo_localizacao

    if tipo_localizacao == 'RURAL_DISTRITO':
        catalog_tipo, catalog_nome = _resolve_rural_localidade_from_catalog(bairro)
        if distrito is None and bairro in RURAL_BAIRROS_LEGADOS:
            distrito = bairro
        elif catalog_tipo == 'DISTRITO' and distrito is None:
            distrito = catalog_nome
        elif catalog_tipo == 'COMUNIDADE' and comunidade_localidade is None:
            comunidade_localidade = catalog_nome
        normalized['distrito'] = distrito
        normalized['comunidade_localidade'] = comunidade_localidade
        normalized['bairro'] = '' if 'bairro' in normalized or bairro is not None else normalized.get('bairro', '')
    else:
        normalized['bairro'] = bairro or ''
        if 'distrito' in normalized:
            normalized['distrito'] = None
        if 'comunidade_localidade' in normalized:
            normalized['comunidade_localidade'] = None

    return normalized


def normalize_documento_anexo_tipo(tipo_documento):
    tipo = _normalize_text(tipo_documento)
    if tipo is None:
        return None
    return DOCUMENTO_TIPO_ALIASES.get(tipo, tipo)


def _collapse_spaces(value):
    value = _normalize_text(value)
    if value is None:
        return None
    return ' '.join(str(value).split())


def normalize_localidade_nome(value):
    value = _collapse_spaces(value)
    if value is None:
        return None
    return value.upper()


def normalize_rua_nome(value):
    value = _collapse_spaces(value)
    if value is None:
        return None

    upper_value = value.upper()
    replacements = {
        'AV. ': 'AVENIDA ',
        'AV ': 'AVENIDA ',
        'TRAV. ': 'TRAVESSA ',
        'TRAV ': 'TRAVESSA ',
        'TV. ': 'TRAVESSA ',
        'TV ': 'TRAVESSA ',
    }
    for prefix, replacement in replacements.items():
        if upper_value.startswith(prefix):
            upper_value = replacement + upper_value[len(prefix):]
            break
    return ' '.join(upper_value.split())


def validate_nome_endereco(value, field_label):
    normalized = _collapse_spaces(value)
    if normalized is None:
        raise serializers.ValidationError(f'Informe uma {field_label} válida.')
    if normalized.upper() in INVALID_ENDERECO_VALUES:
        raise serializers.ValidationError(f'Informe uma {field_label} válida.')
    return normalized


class SincronizacaoMixin:
    def to_internal_value(self, data):
        incoming = data.copy()

        if 'status_sincronizacao' in incoming:
            value = incoming.get('status_sincronizacao')
            if isinstance(value, str):
                normalized = value.strip().upper()
                aliases = {
                    'SYNCED': 'SINCRONIZADO',
                    'SINCRONIZADO': 'SINCRONIZADO',
                    'PENDING': 'PENDENTE',
                    'PENDENTE': 'PENDENTE',
                    'ERROR': 'ERRO',
                    'ERRO': 'ERRO',
                }
                incoming['status_sincronizacao'] = aliases.get(normalized, normalized)

        for field in ('local_id', 'created_at', 'updated_at', 'deleted'):
            incoming.pop(field, None)

        return super().to_internal_value(incoming)

    def _apply_sync_fields(self, attrs):
        # O servidor é a fonte central. Ao aceitar a gravação, o registro
        # passa a estar sincronizado no backend, independentemente do estado
        # temporário informado pelo cliente local.
        attrs['sincronizado'] = True
        attrs['status_sincronizacao'] = 'SINCRONIZADO'
        attrs['sincronizado_em'] = timezone.now()
        return attrs


class DocumentoSerializer(SincronizacaoMixin, serializers.ModelSerializer):
    class Meta:
        model = Documento
        fields = [
            'id',
            'cpf',
            'rg',
            'rg_orgao',
            'rg_uf',
            'carteira_trabalho',
            'inscricao_eleitoral',
            'zona',
            'secao',
            'sincronizado',
            'status_sincronizacao',
            'sincronizado_em',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ('id', 'criado_em', 'atualizado_em')

    def validate(self, attrs):
        return self._apply_sync_fields(attrs)


class DocumentoAnexoSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    tipo_documento = serializers.SerializerMethodField()
    tipo_documento_legacy = serializers.SerializerMethodField()

    class Meta:
        model = DocumentoAnexo
        fields = [
            'id',
            'tipo_documento',
            'tipo_documento_legacy',
            'nome_arquivo',
            'url',
            'extensao',
            'tamanho_bytes',
            'data_envio',
            'status',
            'sem_documento_no_momento',
            'sincronizado',
            'status_sincronizacao',
            'sincronizado_em',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = fields

    def get_tipo_documento(self, obj):
        return normalize_documento_anexo_tipo(obj.tipo_documento)

    def get_tipo_documento_legacy(self, obj):
        tipo = normalize_documento_anexo_tipo(obj.tipo_documento)
        if tipo == DocumentoAnexo.TIPO_RG_FRENTE:
            return DocumentoAnexo.TIPO_RG
        return tipo

    def get_url(self, obj):
        if not obj.arquivo:
            return None
        url = obj.arquivo.url
        request = self.context.get('request')
        if request is not None:
            return request.build_absolute_uri(url)
        media_url = getattr(settings, 'MEDIA_URL', '/media/')
        return f'{media_url.rstrip("/")}/{obj.arquivo.name}'


class EnderecoSerializer(SincronizacaoMixin, serializers.ModelSerializer):
    class Meta:
        model = Endereco
        fields = [
            'id',
            'tipo_localizacao',
            'logradouro',
            'bairro',
            'distrito',
            'comunidade_localidade',
            'numero',
            'cep',
            'complemento',
            'situacao_imovel',
            'valor_aluguel',
            'material_parede',
            'qtd_comodos',
            'possui_luz',
            'possui_asfalto',
            'possui_lixo',
            'abastecimento_agua',
            'abastecimento_agua_outro',
            'possui_saneamento',
            'iluminacao_publica',
            'risco_inundacao',
            'risco_enchente',
            'risco_deslizamento',
            'possui_doc_posse',
            'doc_posse_descricao',
            'motivo_terceiros',
            'latitude',
            'longitude',
            'precisao_geocodificacao',
            'geocodificacao_status',
            'sincronizado',
            'status_sincronizacao',
            'sincronizado_em',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = (
            'id', 'criado_em', 'atualizado_em',
            'latitude', 'longitude', 'precisao_geocodificacao', 'geocodificacao_status',
        )

    def validate(self, attrs):
        attrs = normalize_endereco_payload(attrs, instance=self.instance)
        attrs = self._apply_sync_fields(attrs)
        tipo_localizacao = attrs.get(
            'tipo_localizacao',
            getattr(self.instance, 'tipo_localizacao', None),
        )
        bairro = _normalize_text(
            attrs.get('bairro', getattr(self.instance, 'bairro', None))
        )
        distrito = _normalize_text(
            attrs.get('distrito', getattr(self.instance, 'distrito', None))
        )
        comunidade_localidade = _normalize_text(
            attrs.get(
                'comunidade_localidade',
                getattr(self.instance, 'comunidade_localidade', None),
            )
        )
        abastecimento_agua = attrs.get(
            'abastecimento_agua',
            getattr(self.instance, 'abastecimento_agua', None),
        )
        abastecimento_agua_outro = attrs.get(
            'abastecimento_agua_outro',
            getattr(self.instance, 'abastecimento_agua_outro', None),
        )

        if abastecimento_agua == 'OUTRO':
            if not str(abastecimento_agua_outro or '').strip():
                raise serializers.ValidationError(
                    {'abastecimento_agua_outro': 'Informe o tipo de abastecimento.'}
                )
        elif 'abastecimento_agua_outro' in attrs:
            attrs['abastecimento_agua_outro'] = None

        if tipo_localizacao == 'RURAL_DISTRITO':
            if not distrito and not comunidade_localidade:
                raise serializers.ValidationError(
                    {
                        'distrito': (
                            'Informe o distrito ou a comunidade/localidade '
                            'para endereço rural/distrito.'
                        )
                    }
                )
            attrs['bairro'] = ''
        else:
            if not bairro:
                raise serializers.ValidationError(
                    {'bairro': 'Informe o bairro para endereço urbano.'}
                )
            attrs['distrito'] = None
            attrs['comunidade_localidade'] = None

        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        normalized = normalize_endereco_payload(data, instance=instance)
        data.update(
            {
                'tipo_localizacao': normalized.get('tipo_localizacao'),
                'bairro': normalized.get('bairro', ''),
                'distrito': normalized.get('distrito'),
                'comunidade_localidade': normalized.get('comunidade_localidade'),
            }
        )
        return data


class FamiliaMembroSerializer(SincronizacaoMixin, serializers.ModelSerializer):
    escola = serializers.CharField(required=False, allow_blank=True, write_only=True)
    sem_cpf = serializers.BooleanField(required=False, write_only=True)

    class Meta:
        model = FamiliaMembro
        fields = [
            'id',
            'local_id',
            'nome_membro',
            'parentesco',
            'cpf_membro',
            'nao_possui_cpf',
            'data_nascimento',
            'sexo',
            'escolaridade',
            'ocupacao',
            'escola',
            'sem_cpf',
            'escola_em_que_estuda',
            'gestante',
            'possui_cartao_sus',
            'possui_deficiencia',
            'qual_deficiencia',
            'possui_doenca_grave',
            'descricao_doenca',
            'uso_substancia_ilicita',
            'descricao_substancia',
            'sincronizado',
            'status_sincronizacao',
            'sincronizado_em',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ('id', 'criado_em', 'atualizado_em')

    def to_internal_value(self, data):
        incoming = data.copy()

        if 'status_sincronizacao' in incoming:
            value = incoming.get('status_sincronizacao')
            if isinstance(value, str):
                normalized = value.strip().upper()
                aliases = {
                    'SYNCED': 'SINCRONIZADO',
                    'SINCRONIZADO': 'SINCRONIZADO',
                    'PENDING': 'PENDENTE',
                    'PENDENTE': 'PENDENTE',
                    'ERROR': 'ERRO',
                    'ERRO': 'ERRO',
                }
                incoming['status_sincronizacao'] = aliases.get(normalized, normalized)

        if 'escola' in incoming and 'escola_em_que_estuda' not in incoming:
            incoming['escola_em_que_estuda'] = incoming.get('escola')

        if 'sem_cpf' in incoming and 'nao_possui_cpf' not in incoming:
            incoming['nao_possui_cpf'] = incoming.get('sem_cpf')

        for field in ('created_at', 'updated_at', 'deleted'):
            incoming.pop(field, None)

        return serializers.ModelSerializer.to_internal_value(self, incoming)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if data.get('cpf_membro') is None:
            data['cpf_membro'] = ''
        data['sem_cpf'] = data.get('nao_possui_cpf', False)
        data['escola'] = data.get('escola_em_que_estuda')
        return data

    def validate(self, attrs):
        attrs = self._apply_sync_fields(attrs)
        attrs.pop('escola', None)
        attrs.pop('sem_cpf', None)
        nao_possui_cpf = attrs.get(
            'nao_possui_cpf',
            getattr(self.instance, 'nao_possui_cpf', False),
        )
        cpf_membro = attrs.get(
            'cpf_membro',
            getattr(self.instance, 'cpf_membro', None),
        )
        sexo = attrs.get(
            'sexo',
            getattr(self.instance, 'sexo', None),
        )
        ocupacao = attrs.get(
            'ocupacao',
            getattr(self.instance, 'ocupacao', None),
        )
        escola_em_que_estuda = attrs.get(
            'escola_em_que_estuda',
            getattr(self.instance, 'escola_em_que_estuda', None),
        )
        possui_deficiencia = attrs.get(
            'possui_deficiencia',
            getattr(self.instance, 'possui_deficiencia', False),
        )
        qual_deficiencia = attrs.get(
            'qual_deficiencia',
            getattr(self.instance, 'qual_deficiencia', None),
        )

        if not str(sexo or '').strip():
            raise serializers.ValidationError(
                {'sexo': 'Informe o sexo do membro da família.'}
            )
        if possui_deficiencia and not str(qual_deficiencia or '').strip():
            raise serializers.ValidationError(
                {'qual_deficiencia': 'Informe a deficiência do membro da família.'}
            )
        if not possui_deficiencia and 'qual_deficiencia' in attrs:
            attrs['qual_deficiencia'] = None

        if nao_possui_cpf:
            attrs['cpf_membro'] = None
        elif cpf_membro is not None and isinstance(cpf_membro, str):
            attrs['cpf_membro'] = cpf_membro.strip() or None

        if str(ocupacao or '').strip().upper() == 'ESTUDANTE':
            if not str(escola_em_que_estuda or '').strip():
                raise serializers.ValidationError(
                    {
                        'escola_em_que_estuda': (
                            'Informe a escola do membro quando a ocupação for estudante.'
                        )
                    }
                )
            attrs['escola_em_que_estuda'] = str(escola_em_que_estuda).strip()
        elif 'escola_em_que_estuda' in attrs:
            attrs['escola_em_que_estuda'] = _normalize_text(escola_em_que_estuda)

        return attrs


class EscolaSerializer(SincronizacaoMixin, serializers.ModelSerializer):
    class Meta:
        model = Escola
        fields = [
            'id',
            'codigo',
            'nome',
            'tipo',
            'zona',
            'sincronizado',
            'status_sincronizacao',
            'sincronizado_em',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ('id', 'criado_em', 'atualizado_em')

    def validate(self, attrs):
        return self._apply_sync_fields(attrs)


class LocalTefeSerializer(SincronizacaoMixin, serializers.ModelSerializer):
    created_at = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()

    class Meta:
        model = LocalTefe
        fields = [
            'id',
            'tipo',
            'nome',
            'ativo',
            'ordem',
            'created_at',
            'updated_at',
            'sincronizado',
            'status_sincronizacao',
            'sincronizado_em',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ('id', 'criado_em', 'atualizado_em')

    def validate(self, attrs):
        return self._apply_sync_fields(attrs)

    def get_created_at(self, obj):
        return int(obj.criado_em.timestamp() * 1000) if getattr(obj, 'criado_em', None) else None

    def get_updated_at(self, obj):
        return int(obj.atualizado_em.timestamp() * 1000) if getattr(obj, 'atualizado_em', None) else None


class LocalidadeSerializer(SincronizacaoMixin, serializers.ModelSerializer):
    created_at = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()

    class Meta:
        model = Localidade
        fields = [
            'id',
            'nome',
            'tipo',
            'criada_automaticamente',
            'created_at',
            'updated_at',
            'sincronizado',
            'status_sincronizacao',
            'sincronizado_em',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ('id', 'criado_em', 'atualizado_em')

    def validate_nome(self, value):
        return normalize_localidade_nome(validate_nome_endereco(value, 'localidade'))

    def validate(self, attrs):
        attrs = self._apply_sync_fields(attrs)
        nome = attrs.get('nome', getattr(self.instance, 'nome', None))
        if nome is None:
            return attrs
        queryset = Localidade.objects.filter(nome=nome)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                {'nome': 'Já existe uma localidade com este nome.'}
            )
        return attrs

    def get_created_at(self, obj):
        return int(obj.criado_em.timestamp() * 1000) if getattr(obj, 'criado_em', None) else None

    def get_updated_at(self, obj):
        return int(obj.atualizado_em.timestamp() * 1000) if getattr(obj, 'atualizado_em', None) else None


class RuaSerializer(SincronizacaoMixin, serializers.ModelSerializer):
    localidade_id = serializers.UUIDField(source='localidade.id', read_only=True)
    localidade_nome = serializers.CharField(source='localidade.nome', read_only=True)
    created_at = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()

    class Meta:
        model = Rua
        fields = [
            'id',
            'nome',
            'localidade',
            'localidade_id',
            'localidade_nome',
            'criada_automaticamente',
            'created_at',
            'updated_at',
            'sincronizado',
            'status_sincronizacao',
            'sincronizado_em',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ('id', 'criado_em', 'atualizado_em')
        validators = []

    def validate_nome(self, value):
        return normalize_rua_nome(validate_nome_endereco(value, 'rua'))

    def validate(self, attrs):
        attrs = self._apply_sync_fields(attrs)
        nome = attrs.get('nome', getattr(self.instance, 'nome', None))
        localidade = attrs.get('localidade', getattr(self.instance, 'localidade', None))
        if nome is None or localidade is None:
            return attrs
        queryset = Rua.objects.filter(localidade=localidade, nome=nome)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                {'nome': 'Já existe uma rua com este nome nesta localidade.'}
            )
        return attrs

    def get_created_at(self, obj):
        return int(obj.criado_em.timestamp() * 1000) if getattr(obj, 'criado_em', None) else None

    def get_updated_at(self, obj):
        return int(obj.atualizado_em.timestamp() * 1000) if getattr(obj, 'atualizado_em', None) else None


class SocioeconomicoSerializer(SincronizacaoMixin, serializers.ModelSerializer):
    servicos_sociais = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
    )
    beneficios_recebidos = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_empty=True,
    )

    class Meta:
        model = Socioeconomico
        fields = [
            'id',
            'renda_total',
            'faixa_renda',
            'precedencia_rendimento',
            'pessoas_com_rendimento',
            'recebe_beneficio',
            'beneficio_nome',
            'beneficio_tipo',
            'beneficio_valor',
            'beneficios_recebidos',
            'quantidade_pessoas_residencia',
            'quantidade_pessoas_estudando',
            'quantidade_criancas',
            'quantidade_adolescentes',
            'quantidade_adultos',
            'quantidade_idosos',
            'ha_gestante',
            'ha_pessoa_com_deficiencia',
            'qual_deficiencia',
            'utiliza_servico_social',
            'servicos_sociais',
            'pretende_voltar_estudar',
            'possui_medida_protetiva',
            'violencia_domestica',
            'eh_ribeirinho',
            'cidadao_estava_em_casa',
            'ja_foi_visitado',
            'mais_de_um_nucleo',
            'documentacao_completa_grupo',
            'observacoes_gerais',
            'sincronizado',
            'status_sincronizacao',
            'sincronizado_em',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ('id', 'criado_em', 'atualizado_em')

    def to_internal_value(self, data):
        incoming = data.copy()
        legacy_service_value = incoming.get('utiliza_servico_social')

        renda_total = incoming.get('renda_total')
        if renda_total in (None, ''):
            incoming['renda_total'] = '0.00'
        elif isinstance(renda_total, str):
            incoming['renda_total'] = renda_total.strip() or '0.00'

        if isinstance(legacy_service_value, str):
            value = legacy_service_value.strip()
            if value.upper() in {'TRUE', 'FALSE'}:
                incoming['utiliza_servico_social'] = value.upper() == 'TRUE'
            elif value:
                incoming['utiliza_servico_social'] = True
                incoming.setdefault('servicos_sociais', [value])

        if incoming.get('servicos_sociais') in (None, ''):
            incoming['servicos_sociais'] = []

        pessoas_com_rendimento = incoming.get('pessoas_com_rendimento')
        if pessoas_com_rendimento in (None, ''):
            incoming['pessoas_com_rendimento'] = 1
        else:
            try:
                pessoas_int = int(pessoas_com_rendimento)
            except (TypeError, ValueError):
                pessoas_int = 1
            incoming['pessoas_com_rendimento'] = max(pessoas_int, 1)

        return super().to_internal_value(incoming)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['beneficios_recebidos'] = self._serialize_beneficios_recebidos(
            getattr(instance, 'beneficios_recebidos', None),
            getattr(instance, 'beneficio_nome', None),
            getattr(instance, 'beneficio_tipo', None),
            getattr(instance, 'beneficio_valor', None),
            getattr(instance, 'recebe_beneficio', False),
        )
        return data

    def _serialize_beneficios_recebidos(
        self,
        beneficios_recebidos,
        beneficio_nome,
        beneficio_tipo,
        beneficio_valor,
        recebe_beneficio,
    ):
        beneficios = self._normalize_beneficios_recebidos(
            beneficios_recebidos,
            allow_partial=False,
        )

        if not beneficios and recebe_beneficio and (
            beneficio_nome or beneficio_tipo or beneficio_valor not in (None, '')
        ):
            beneficios = self._normalize_beneficios_recebidos(
                [
                    {
                        'beneficio_nome': beneficio_nome,
                        'beneficio_tipo': beneficio_tipo,
                        'beneficio_valor': beneficio_valor,
                    }
                ],
                allow_partial=True,
            )

        return beneficios

    def _normalize_beneficios_recebidos(self, beneficios_recebidos, allow_partial):
        normalized = []

        for item in beneficios_recebidos or []:
            if not isinstance(item, dict):
                raise serializers.ValidationError(
                    {'beneficios_recebidos': 'Cada benefício deve ser um objeto.'}
                )

            nome = item.get('beneficio_nome', item.get('nome'))
            tipo = item.get('beneficio_tipo', item.get('tipo'))
            valor = item.get('beneficio_valor', item.get('valor'))

            if isinstance(nome, str):
                nome = nome.strip() or None
            elif nome is not None:
                nome = str(nome).strip() or None

            if isinstance(tipo, str):
                tipo = tipo.strip() or None
            elif tipo is not None:
                tipo = str(tipo).strip() or None

            if valor in ('', None):
                valor_decimal = None
            else:
                try:
                    valor_decimal = Decimal(str(valor))
                except (InvalidOperation, TypeError, ValueError):
                    raise serializers.ValidationError(
                        {'beneficios_recebidos': 'Valor inválido em beneficios_recebidos.'}
                    )

            if not allow_partial and (bool(tipo) != bool(valor_decimal is not None)):
                raise serializers.ValidationError(
                    {
                        'beneficios_recebidos': (
                            'Cada benefício deve ter tipo e valor preenchidos juntos.'
                        )
                    }
                )

            if not allow_partial and not tipo and valor_decimal is None and not nome:
                continue

            normalized_item = {
                'nome': nome,
                'tipo': tipo,
                'valor': f'{valor_decimal:.2f}' if valor_decimal is not None else None,
                'beneficio_nome': nome,
                'beneficio_tipo': tipo,
                'beneficio_valor': (
                    f'{valor_decimal:.2f}' if valor_decimal is not None else None
                ),
            }
            normalized.append(normalized_item)

        return normalized

    def validate(self, attrs):
        attrs = self._apply_sync_fields(attrs)

        beneficios_recebidos = attrs.get('beneficios_recebidos', serializers.empty)
        if beneficios_recebidos is serializers.empty:
            beneficios_recebidos = getattr(self.instance, 'beneficios_recebidos', None)
        normalized_beneficios = self._normalize_beneficios_recebidos(
            beneficios_recebidos,
            allow_partial=False,
        )

        recebe_beneficio = attrs.get(
            'recebe_beneficio',
            getattr(self.instance, 'recebe_beneficio', False),
        )
        beneficio_nome = attrs.get(
            'beneficio_nome',
            getattr(self.instance, 'beneficio_nome', None),
        )
        beneficio_tipo = attrs.get(
            'beneficio_tipo',
            getattr(self.instance, 'beneficio_tipo', None),
        )
        beneficio_valor = attrs.get(
            'beneficio_valor',
            getattr(self.instance, 'beneficio_valor', None),
        )

        if recebe_beneficio:
            errors = {}
            if normalized_beneficios:
                primeiro_beneficio = normalized_beneficios[0]
                beneficio_nome = primeiro_beneficio.get('beneficio_nome')
                beneficio_tipo = primeiro_beneficio.get('beneficio_tipo')
                beneficio_valor = primeiro_beneficio.get('beneficio_valor')
            if not str(beneficio_tipo or '').strip():
                errors['beneficio_tipo'] = 'Este campo é obrigatório quando recebe_beneficio=true.'
            if beneficio_valor in (None, ''):
                errors['beneficio_valor'] = 'Este campo é obrigatório quando recebe_beneficio=true.'
            if errors:
                raise serializers.ValidationError(errors)
        else:
            attrs['beneficio_nome'] = None
            attrs['beneficio_tipo'] = None
            attrs['beneficio_valor'] = None

        if not recebe_beneficio and 'beneficio_nome' in attrs:
            attrs['beneficio_nome'] = None
        elif beneficio_nome is not None and isinstance(beneficio_nome, str):
            attrs['beneficio_nome'] = beneficio_nome.strip() or None

        if normalized_beneficios:
            attrs['beneficios_recebidos'] = normalized_beneficios
            attrs['recebe_beneficio'] = True
            attrs['beneficio_nome'] = normalized_beneficios[0]['beneficio_nome']
            attrs['beneficio_tipo'] = normalized_beneficios[0]['beneficio_tipo']
            attrs['beneficio_valor'] = normalized_beneficios[0]['beneficio_valor']
        elif recebe_beneficio:
            attrs['recebe_beneficio'] = True
            attrs['beneficios_recebidos'] = self._normalize_beneficios_recebidos(
                [
                    {
                        'beneficio_nome': attrs.get('beneficio_nome', beneficio_nome),
                        'beneficio_tipo': attrs.get('beneficio_tipo', beneficio_tipo),
                        'beneficio_valor': attrs.get('beneficio_valor', beneficio_valor),
                    }
                ],
                allow_partial=True,
            )
        else:
            attrs['recebe_beneficio'] = False
            attrs['beneficios_recebidos'] = []

        ha_pessoa_com_deficiencia = attrs.get(
            'ha_pessoa_com_deficiencia',
            getattr(self.instance, 'ha_pessoa_com_deficiencia', False),
        )
        qual_deficiencia = attrs.get(
            'qual_deficiencia',
            getattr(self.instance, 'qual_deficiencia', None),
        )

        if ha_pessoa_com_deficiencia and not str(qual_deficiencia or '').strip():
            raise serializers.ValidationError(
                {'qual_deficiencia': 'Informe a deficiência quando houver pessoa com deficiência.'}
            )
        if not ha_pessoa_com_deficiencia:
            attrs['qual_deficiencia'] = None

        utiliza_servico_social = attrs.get(
            'utiliza_servico_social',
            getattr(self.instance, 'utiliza_servico_social', False),
        )
        servicos_sociais = attrs.get(
            'servicos_sociais',
            getattr(self.instance, 'servicos_sociais', []),
        ) or []

        if utiliza_servico_social:
            attrs['servicos_sociais'] = servicos_sociais
        else:
            attrs['servicos_sociais'] = []

        return attrs


class TermoResponsabilidadeSerializer(SincronizacaoMixin, serializers.ModelSerializer):
    class Meta:
        model = TermoResponsabilidade
        fields = [
            'id',
            'nome_responsavel',
            'funcao',
            'local_termo',
            'data_termo',
            'hora_termo',
            'sincronizado',
            'status_sincronizacao',
            'sincronizado_em',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ('id', 'criado_em', 'atualizado_em')

    def validate(self, attrs):
        return self._apply_sync_fields(attrs)


class CidadaoSerializer(SincronizacaoMixin, serializers.ModelSerializer):
    status = serializers.CharField(required=False, allow_blank=True, write_only=True)
    local_id = serializers.CharField(required=False, allow_blank=True, write_only=True)
    created_at = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()
    deleted = serializers.BooleanField(required=False, write_only=True)
    bairro = serializers.CharField(required=False, allow_blank=True, write_only=True)
    pretende_voltar_estudar = serializers.BooleanField(required=False, write_only=True)
    possui_medida_protetiva = serializers.BooleanField(required=False, write_only=True)
    violencia_domestica = serializers.BooleanField(required=False, write_only=True)
    eh_ribeirinho = serializers.BooleanField(required=False, write_only=True)
    cidadao_estava_em_casa = serializers.BooleanField(required=False, write_only=True)
    ja_foi_visitado = serializers.BooleanField(required=False, write_only=True)
    documentos = DocumentoSerializer(required=False, allow_null=True)
    documentos_anexados = DocumentoAnexoSerializer(many=True, read_only=True)
    documentosAnexados = serializers.SerializerMethodField()
    documento_pdf = serializers.SerializerMethodField()
    endereco = EnderecoSerializer(required=False, allow_null=True)
    socioeconomico = SocioeconomicoSerializer(required=False, allow_null=True)
    membros_familia = FamiliaMembroSerializer(many=True, required=False)
    termo_responsabilidade = TermoResponsabilidadeSerializer(required=False, allow_null=True)
    nome_responsavel = serializers.CharField(
        source='termo_responsabilidade.nome_responsavel',
        read_only=True,
    )
    local_termo = serializers.CharField(
        source='termo_responsabilidade.local_termo',
        read_only=True,
    )
    data_termo = serializers.CharField(
        source='termo_responsabilidade.data_termo',
        read_only=True,
    )
    hora_termo = serializers.CharField(
        source='termo_responsabilidade.hora_termo',
        read_only=True,
    )
    pendente_sincronizacao = serializers.SerializerMethodField()
    nao_sincronizado = serializers.SerializerMethodField()
    atualizado_por_nome = serializers.SerializerMethodField()
    situacaoBeneficiario = serializers.SerializerMethodField()

    class Meta:
        model = Cidadao
        fields = [
            'id',
            'nome',
            'status',
            'local_id',
            'created_at',
            'updated_at',
            'deleted',
            'nis',
            'data_nascimento',
            'telefone',
            'email',
            'naturalidade',
            'ocupacao',
            'possui_carteira_trabalho',
            'encaminhamentos',
            'escolaridade',
            'identidade_genero',
            'cor',
            'possui_deficiencia',
            'estado_civil',
            'autorizacao_uso_imagem',
            'autorizacao_uso_imagem_aceite_em',
            'autorizacao_uso_imagem_responsavel',
            'tempo_residencia',
            'bairro',
            'pretende_voltar_estudar',
            'possui_medida_protetiva',
            'violencia_domestica',
            'eh_ribeirinho',
            'cidadao_estava_em_casa',
            'ja_foi_visitado',
            'atualizado_por',
            'atualizado_por_nome',
            'sincronizado',
            'status_sincronizacao',
            'sincronizado_em',
            'status_atualizacao',
            'pendente_sincronizacao',
            'nao_sincronizado',
            'situacaoBeneficiario',
            'documentos',
            'documentos_anexados',
            'documentosAnexados',
            'documento_pdf',
            'endereco',
            'socioeconomico',
            'membros_familia',
            'termo_responsabilidade',
            'nome_responsavel',
            'local_termo',
            'data_termo',
            'hora_termo',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = (
            'id',
            'criado_em',
            'atualizado_em',
            'pendente_sincronizacao',
            'nao_sincronizado',
            'status_atualizacao',
            'nome_responsavel',
            'local_termo',
            'data_termo',
            'hora_termo',
            'atualizado_por',
            'atualizado_por_nome',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        instance = getattr(self, 'instance', None)
        if instance is None or not isinstance(instance, Cidadao):
            return

        # Passa as instancias aninhadas atuais para que validacoes de update,
        # como unique no CPF, reconhecam o proprio registro.
        nested_instances = {
            'documentos': getattr(instance, 'documentos', None),
            'endereco': getattr(instance, 'endereco', None),
            'socioeconomico': getattr(instance, 'socioeconomico', None),
            'termo_responsabilidade': getattr(instance, 'termo_responsabilidade', None),
        }

        for field_name, nested_instance in nested_instances.items():
            try:
                self.fields[field_name].instance = nested_instance
            except Exception:
                continue

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_pendente_sincronizacao(self, obj):
        return obj.status_sincronizacao == 'PENDENTE'

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_nao_sincronizado(self, obj):
        return obj.status_sincronizacao != 'SINCRONIZADO'

    def get_atualizado_por_nome(self, obj):
        user = getattr(obj, 'atualizado_por', None)
        if not user:
            return None
        name = user.get_full_name().strip()
        return name or user.get_username()

    def get_created_at(self, obj):
        return int(obj.criado_em.timestamp() * 1000) if getattr(obj, 'criado_em', None) else None

    def get_updated_at(self, obj):
        return int(obj.atualizado_em.timestamp() * 1000) if getattr(obj, 'atualizado_em', None) else None

    def get_situacaoBeneficiario(self, obj):
        vinculos_prefetched = getattr(obj, 'beneficios_recebidos_ordenados', None)
        if vinculos_prefetched is not None:
            vinculo = vinculos_prefetched[0] if vinculos_prefetched else None
            return vinculo.status if vinculo else None

        vinculo = obj.beneficios_recebidos.order_by('criado_em').first()
        return vinculo.status if vinculo else None

    def get_documentosAnexados(self, obj):
        serializer = DocumentoAnexoSerializer(
            obj.documentos_anexados.all(),
            many=True,
            context=self.context,
        )
        return serializer.data

    def get_documento_pdf(self, obj):
        arquivo = getattr(obj, 'documento_pdf', None)
        if not arquivo:
            return None

        url = arquivo.url
        request = self.context.get('request')
        if request is not None:
            url = request.build_absolute_uri(url)

        return {
            'url': url,
            'nome_arquivo': getattr(obj, 'documento_pdf_nome_arquivo', '')
            or Path(arquivo.name).name,
            'status': 'SINCRONIZADO' if arquivo.name else 'PENDENTE',
        }

    def _normalize_nullable_unique_fields(self, attrs):
        for field in ('nis', 'email'):
            if field in attrs:
                value = attrs.get(field)
                if value is None:
                    continue
                if isinstance(value, str) and not value.strip():
                    attrs[field] = None
        return attrs

    def to_internal_value(self, data):
        incoming = data.copy()

        termo_flat_fields = (
            'nome_responsavel',
            'local_termo',
            'data_termo',
            'hora_termo',
        )
        flat_payload = {
            field: incoming.get(field)
            for field in termo_flat_fields
            if field in incoming
        }
        if flat_payload and 'termo_responsabilidade' not in incoming:
            incoming['termo_responsabilidade'] = flat_payload

        socioeconomico_flat_fields = (
            'pretende_voltar_estudar',
            'possui_medida_protetiva',
            'violencia_domestica',
            'eh_ribeirinho',
            'cidadao_estava_em_casa',
            'ja_foi_visitado',
        )
        socioeconomico_flat_payload = {
            field: incoming.get(field)
            for field in socioeconomico_flat_fields
            if field in incoming
        }
        if socioeconomico_flat_payload:
            socioeconomico_payload = incoming.get('socioeconomico')
            if not isinstance(socioeconomico_payload, dict):
                socioeconomico_payload = {}
            for field, value in socioeconomico_flat_payload.items():
                socioeconomico_payload.setdefault(field, value)
            incoming['socioeconomico'] = socioeconomico_payload

        bairro = incoming.get('bairro')
        if bairro is not None:
            endereco_payload = incoming.get('endereco')
            if not isinstance(endereco_payload, dict):
                endereco_payload = {}
            endereco_payload.setdefault('bairro', bairro)
            incoming['endereco'] = endereco_payload

        endereco_payload = incoming.get('endereco')
        if isinstance(endereco_payload, dict):
            incoming['endereco'] = normalize_endereco_payload(
                endereco_payload,
                instance=getattr(self.instance, 'endereco', None) if getattr(self, 'instance', None) else None,
            )

        return super().to_internal_value(incoming)

    def validate(self, attrs):
        attrs = self._normalize_nullable_unique_fields(attrs)
        attrs.pop('status', None)
        attrs.pop('local_id', None)
        attrs.pop('created_at', None)
        attrs.pop('updated_at', None)
        attrs.pop('deleted', None)
        attrs.pop('bairro', None)
        attrs.pop('pretende_voltar_estudar', None)
        attrs.pop('possui_medida_protetiva', None)
        attrs.pop('violencia_domestica', None)
        attrs.pop('eh_ribeirinho', None)
        attrs.pop('cidadao_estava_em_casa', None)
        attrs.pop('ja_foi_visitado', None)
        return self._apply_sync_fields(attrs)

    def create(self, validated_data):
        documento_data = validated_data.pop('documentos', None)
        endereco_data = validated_data.pop('endereco', None)
        socioeconomico_data = validated_data.pop('socioeconomico', None)
        membros_familia_data = validated_data.pop('membros_familia', [])
        termo_responsabilidade_data = validated_data.pop('termo_responsabilidade', None)

        with transaction.atomic():
            cidadao = Cidadao.objects.create(**validated_data)

            if documento_data:
                Documento.objects.create(cidadao=cidadao, **documento_data)
            if endereco_data:
                Endereco.objects.create(cidadao=cidadao, **endereco_data)
            if socioeconomico_data:
                Socioeconomico.objects.create(cidadao=cidadao, **socioeconomico_data)
            if membros_familia_data:
                FamiliaMembro.objects.bulk_create(
                    [
                        FamiliaMembro(cidadao_titular=cidadao, **membro_data)
                        for membro_data in membros_familia_data
                    ]
                )
            if termo_responsabilidade_data:
                TermoResponsabilidade.objects.create(
                    cidadao=cidadao,
                    **termo_responsabilidade_data,
                )

            cidadao.refresh_from_db()

        return cidadao

    def update(self, instance, validated_data):
        documento_data = validated_data.pop('documentos', None)
        endereco_data = validated_data.pop('endereco', None)
        socioeconomico_data = validated_data.pop('socioeconomico', None)
        membros_familia_data = validated_data.pop('membros_familia', None)
        termo_responsabilidade_data = validated_data.pop('termo_responsabilidade', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if documento_data is not None:
            documento, _ = Documento.objects.get_or_create(cidadao=instance)
            for attr, value in documento_data.items():
                setattr(documento, attr, value)
            documento.save()

        if endereco_data is not None:
            endereco, _ = Endereco.objects.get_or_create(cidadao=instance)
            for attr, value in endereco_data.items():
                setattr(endereco, attr, value)
            endereco.save()

        if socioeconomico_data is not None:
            socioeconomico, _ = Socioeconomico.objects.get_or_create(
                cidadao=instance
            )
            for attr, value in socioeconomico_data.items():
                setattr(socioeconomico, attr, value)
            socioeconomico.save()

        if termo_responsabilidade_data is not None:
            termo_responsabilidade, _ = TermoResponsabilidade.objects.get_or_create(
                cidadao=instance
            )
            for attr, value in termo_responsabilidade_data.items():
                setattr(termo_responsabilidade, attr, value)
            termo_responsabilidade.save()

        if membros_familia_data is not None:
            existing = {str(item.id): item for item in instance.membros_familia.all()}
            enviados = set()

            for membro_data in membros_familia_data:
                membro_id = membro_data.pop('id', None)
                if membro_id and str(membro_id) in existing:
                    membro = existing[str(membro_id)]
                    for attr, value in membro_data.items():
                        setattr(membro, attr, value)
                    membro.save()
                    enviados.add(str(membro.id))
                else:
                    novo = FamiliaMembro.objects.create(
                        cidadao_titular=instance,
                        **membro_data,
                    )
                    enviados.add(str(novo.id))

            for membro_id, membro in existing.items():
                if membro_id not in enviados:
                    membro.delete()

        instance.refresh_from_db()

        return instance


class CidadaoListSerializer(serializers.ModelSerializer):
    documentos = DocumentoSerializer(read_only=True)
    endereco = EnderecoSerializer(read_only=True)
    atualizado_por_nome = serializers.SerializerMethodField()
    pendente_sincronizacao = serializers.SerializerMethodField()
    nao_sincronizado = serializers.SerializerMethodField()

    class Meta:
        model = Cidadao
        fields = [
            'id',
            'nome',
            'nis',
            'data_nascimento',
            'telefone',
            'email',
            'identidade_genero',
            'sincronizado',
            'status_sincronizacao',
            'sincronizado_em',
            'atualizado_por_nome',
            'status_atualizacao',
            'pendente_sincronizacao',
            'nao_sincronizado',
            'documentos',
            'endereco',
            'criado_em',
            'atualizado_em',
        ]

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_pendente_sincronizacao(self, obj):
        return obj.status_sincronizacao == 'PENDENTE'

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_nao_sincronizado(self, obj):
        return obj.status_sincronizacao != 'SINCRONIZADO'

    def get_atualizado_por_nome(self, obj):
        user = getattr(obj, 'atualizado_por', None)
        if not user:
            return None
        name = user.get_full_name().strip()
        return name or user.get_username()


class BeneficioSerializer(SincronizacaoMixin, serializers.ModelSerializer):
    atualizado_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = Beneficio
        fields = [
            'id',
            'nome',
            'descricao',
            'icone',
            'ativo',
            'atualizado_por',
            'atualizado_por_nome',
            'sincronizado',
            'status_sincronizacao',
            'sincronizado_em',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ('id', 'atualizado_por', 'atualizado_por_nome')

    def validate(self, attrs):
        return self._apply_sync_fields(attrs)

    def get_atualizado_por_nome(self, obj):
        user = getattr(obj, 'atualizado_por', None)
        if not user:
            return None
        name = user.get_full_name().strip()
        return name or user.get_username()


class BeneficiarioSerializer(SincronizacaoMixin, serializers.ModelSerializer):
    beneficio_id = serializers.UUIDField(source='beneficio.id', read_only=True)
    cidadao_id = serializers.UUIDField(source='cidadao.id', read_only=True)
    vinculo_id = serializers.UUIDField(source='id', read_only=True)
    cidadao_nome = serializers.CharField(source='cidadao.nome', read_only=True)
    beneficio_nome = serializers.CharField(source='beneficio.nome', read_only=True)
    nome = serializers.CharField(source='beneficio.nome', read_only=True)
    beneficioNome = serializers.CharField(source='beneficio.nome', read_only=True)
    ativo = serializers.BooleanField(source='beneficio.ativo', read_only=True)
    beneficio_ativo = serializers.BooleanField(source='beneficio.ativo', read_only=True)
    beneficio_status = serializers.CharField(source='status', read_only=True)
    atualizado_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = Beneficiario
        fields = [
            'id',
            'vinculo_id',
            'cidadao',
            'cidadao_id',
            'cidadao_nome',
            'beneficio',
            'beneficio_id',
            'beneficio_nome',
            'nome',
            'beneficioNome',
            'ativo',
            'beneficio_ativo',
            'beneficio_status',
            'status',
            'valor_recebido',
            'data_solicitacao',
            'atualizado_por',
            'atualizado_por_nome',
            'sincronizado',
            'status_sincronizacao',
            'sincronizado_em',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = (
            'id',
            'data_solicitacao',
            'criado_em',
            'atualizado_em',
            'atualizado_por',
            'atualizado_por_nome',
        )
        validators = []

    def validate(self, attrs):
        attrs = self._apply_sync_fields(attrs)
        cidadao = attrs.get('cidadao', getattr(self.instance, 'cidadao', None))
        beneficio = attrs.get('beneficio', getattr(self.instance, 'beneficio', None))

        if cidadao and beneficio:
            queryset = Beneficiario.objects.filter(
                cidadao=cidadao,
                beneficio=beneficio,
            )
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise serializers.ValidationError(
                    {
                        'non_field_errors': [
                            'Este cidadão já está vinculado a este benefício.'
                        ]
                    }
                )

        return attrs

    def get_atualizado_por_nome(self, obj):
        user = getattr(obj, 'atualizado_por', None)
        if not user:
            return None
        name = user.get_full_name().strip()
        return name or user.get_username()


class BeneficioCidadaoSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source='cidadao.id', read_only=True)
    vinculo_id = serializers.UUIDField(source='id', read_only=True)
    beneficio_id = serializers.UUIDField(source='beneficio.id', read_only=True)
    cidadao_id = serializers.UUIDField(source='cidadao.id', read_only=True)
    nome = serializers.CharField(source='cidadao.nome', read_only=True)
    email = serializers.CharField(source='cidadao.email', read_only=True)
    nis = serializers.CharField(source='cidadao.nis', read_only=True)
    cpf = serializers.CharField(source='cidadao.documentos.cpf', read_only=True)
    data_nascimento = serializers.DateField(
        source='cidadao.data_nascimento',
        read_only=True,
    )

    class Meta:
        model = Beneficiario
        fields = [
            'id',
            'vinculo_id',
            'beneficio_id',
            'cidadao_id',
            'nome',
            'email',
            'nis',
            'cpf',
            'data_nascimento',
            'status',
        ]
