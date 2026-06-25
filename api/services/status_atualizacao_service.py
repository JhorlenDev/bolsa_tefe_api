from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone


STATUS_ATUALIZACAO_PENDENTE = 'PENDENTE'
STATUS_ATUALIZACAO_ATUALIZADO = 'ATUALIZADO'
STATUS_ATUALIZACAO_DESATUALIZADO = 'DESATUALIZADO'

VALORES_CADASTRAIS_INVALIDOS = {
    '',
    '-',
    '--',
    'NAO_INFORMADO',
    'NÃO INFORMADO',
    'NAO INFORMADO',
    'N/I',
    'NI',
    'NULL',
    'NONE',
}

CAMPOS_CADASTRAIS_DESATUALIZADOS = (
    'naturalidade',
    'cor',
    'escolaridade',
    'identidade_genero',
    'estado_civil',
)

DOCUMENTOS_OBRIGATORIOS = (
    'rg_frente',
    'rg_verso',
    'cpf',
    'certidao_nascimento',
    'quitacao_eleitoral',
    'comprovante_residencia',
)

DOCUMENTOS_OBRIGATORIOS_ALIASES = {
    'rg_frente': {'rg_frente', 'rg'},
    'rg_verso': {'rg_verso'},
    'cpf': {'cpf'},
    'certidao_nascimento': {'certidao_nascimento'},
    'quitacao_eleitoral': {'quitacao_eleitoral', 'certidao_quitacao_eleitoral'},
    'comprovante_residencia': {'comprovante_residencia'},
}


def _texto(valor):
    if valor is None:
        return ''
    return str(valor).strip()


def _eh_preenchido(valor):
    if isinstance(valor, bool):
        return valor
    if valor is None:
        return False
    if isinstance(valor, (int, float)):
        return True
    return _texto(valor) != ''


def _valor_cadastral_desatualizado(valor):
    texto = _texto(valor)
    if texto == '':
        return True
    return texto.upper() in VALORES_CADASTRAIS_INVALIDOS


def _tem_cadastro_basico_desatualizado(cidadao):
    return any(
        _valor_cadastral_desatualizado(getattr(cidadao, campo, None))
        for campo in CAMPOS_CADASTRAIS_DESATUALIZADOS
    )


def _relacionamento(cidadao, nome_relacao):
    try:
        return getattr(cidadao, nome_relacao)
    except ObjectDoesNotExist:
        return None


def _documentos_anexados(cidadao):
    try:
        return list(cidadao.documentos_anexados.all())
    except ObjectDoesNotExist:
        return []
    except AttributeError:
        return []


def _documento_anexo_tem_arquivo(documento):
    arquivo = getattr(documento, 'arquivo', None)
    if arquivo is None:
        return False
    nome = getattr(arquivo, 'name', '') if hasattr(arquivo, 'name') else arquivo
    return _texto(nome) != ''


def _documento_obrigatorio_satisfeito(documentos, tipo_obrigatorio):
    aliases = DOCUMENTOS_OBRIGATORIOS_ALIASES[tipo_obrigatorio]
    for documento in documentos:
        tipo_documento = _texto(getattr(documento, 'tipo_documento', '')).lower()
        if tipo_documento not in aliases:
            continue
        if _documento_anexo_tem_arquivo(documento):
            return True
        if getattr(documento, 'sem_documento_no_momento', False) is True:
            return True
    return False


def calcular_status_atualizacao_cidadao(cidadao):
    if cidadao is None:
        return STATUS_ATUALIZACAO_PENDENTE

    if not _eh_preenchido(getattr(cidadao, 'nome', None)):
        return STATUS_ATUALIZACAO_PENDENTE
    if not _eh_preenchido(getattr(cidadao, 'data_nascimento', None)):
        return STATUS_ATUALIZACAO_PENDENTE
    if _tem_cadastro_basico_desatualizado(cidadao):
        return STATUS_ATUALIZACAO_DESATUALIZADO
    if not _eh_preenchido(getattr(cidadao, 'naturalidade', None)):
        return STATUS_ATUALIZACAO_PENDENTE
    if not _eh_preenchido(getattr(cidadao, 'escolaridade', None)):
        return STATUS_ATUALIZACAO_PENDENTE
    if not _eh_preenchido(getattr(cidadao, 'identidade_genero', None)):
        return STATUS_ATUALIZACAO_PENDENTE
    if not _eh_preenchido(getattr(cidadao, 'cor', None)):
        return STATUS_ATUALIZACAO_PENDENTE
    if not _eh_preenchido(getattr(cidadao, 'estado_civil', None)):
        return STATUS_ATUALIZACAO_PENDENTE
    if getattr(cidadao, 'autorizacao_uso_imagem', False) is not True:
        return STATUS_ATUALIZACAO_PENDENTE

    documentos = _relacionamento(cidadao, 'documentos')
    if documentos is None or not _eh_preenchido(getattr(documentos, 'cpf', None)):
        return STATUS_ATUALIZACAO_PENDENTE

    endereco = _relacionamento(cidadao, 'endereco')
    if endereco is None:
        return STATUS_ATUALIZACAO_PENDENTE
    if not _eh_preenchido(getattr(endereco, 'tipo_localizacao', None)):
        return STATUS_ATUALIZACAO_PENDENTE
    if not _eh_preenchido(getattr(endereco, 'logradouro', None)):
        return STATUS_ATUALIZACAO_PENDENTE

    tipo_localizacao = _texto(getattr(endereco, 'tipo_localizacao', '')).upper()
    bairro = _texto(getattr(endereco, 'bairro', None))
    distrito = _texto(getattr(endereco, 'distrito', None))
    comunidade = _texto(getattr(endereco, 'comunidade_localidade', None))

    if tipo_localizacao == 'RURAL_DISTRITO':
        # Rural aceita distrito OU comunidade (e legado rural com bairro preenchido).
        if not (
            _eh_preenchido(distrito)
            or _eh_preenchido(comunidade)
            or _eh_preenchido(bairro)
        ):
            return STATUS_ATUALIZACAO_PENDENTE
    else:
        if not _eh_preenchido(bairro):
            return STATUS_ATUALIZACAO_PENDENTE

    if not _eh_preenchido(getattr(endereco, 'numero', None)):
        return STATUS_ATUALIZACAO_PENDENTE
    if not _eh_preenchido(getattr(endereco, 'situacao_imovel', None)):
        return STATUS_ATUALIZACAO_PENDENTE
    if not _eh_preenchido(getattr(endereco, 'complemento', None)):
        return STATUS_ATUALIZACAO_PENDENTE
    if not _eh_preenchido(getattr(endereco, 'material_parede', None)):
        return STATUS_ATUALIZACAO_PENDENTE
    if int(getattr(endereco, 'qtd_comodos', 0) or 0) <= 0:
        return STATUS_ATUALIZACAO_PENDENTE
    if not _eh_preenchido(getattr(endereco, 'abastecimento_agua', None)):
        return STATUS_ATUALIZACAO_PENDENTE

    abastecimento = _texto(getattr(endereco, 'abastecimento_agua', '')).upper()
    if abastecimento == 'OUTRO' and not _eh_preenchido(
        getattr(endereco, 'abastecimento_agua_outro', None)
    ):
        return STATUS_ATUALIZACAO_PENDENTE

    socioeconomico = _relacionamento(cidadao, 'socioeconomico')
    if socioeconomico is None:
        return STATUS_ATUALIZACAO_PENDENTE
    if not _eh_preenchido(getattr(socioeconomico, 'renda_total', None)):
        return STATUS_ATUALIZACAO_PENDENTE
    if not _eh_preenchido(getattr(socioeconomico, 'precedencia_rendimento', None)):
        return STATUS_ATUALIZACAO_PENDENTE
    pessoas_com_rendimento = int(
        getattr(socioeconomico, 'pessoas_com_rendimento', 0) or 0
    )
    if pessoas_com_rendimento <= 0:
        return STATUS_ATUALIZACAO_PENDENTE

    termo = _relacionamento(cidadao, 'termo_responsabilidade')
    if termo is None:
        return STATUS_ATUALIZACAO_PENDENTE
    if not _eh_preenchido(getattr(termo, 'hora_termo', None)):
        return STATUS_ATUALIZACAO_PENDENTE

    documentos_anexados = _documentos_anexados(cidadao)
    for tipo_obrigatorio in DOCUMENTOS_OBRIGATORIOS:
        if not _documento_obrigatorio_satisfeito(documentos_anexados, tipo_obrigatorio):
            return STATUS_ATUALIZACAO_PENDENTE

    return STATUS_ATUALIZACAO_ATUALIZADO


def salvar_status_atualizacao_cidadao(cidadao):
    status_atualizacao = calcular_status_atualizacao_cidadao(cidadao)
    if cidadao is None:
        return status_atualizacao

    agora = timezone.now()
    modelo = cidadao.__class__
    if getattr(cidadao, 'pk', None) is not None:
        modelo.objects.filter(pk=cidadao.pk).update(
            status_atualizacao=status_atualizacao,
            atualizado_em=agora,
        )
    setattr(cidadao, 'status_atualizacao', status_atualizacao)
    setattr(cidadao, 'atualizado_em', agora)

    return status_atualizacao


def recalcular_status_atualizacao_por_id(cidadao_id):
    if not cidadao_id:
        return STATUS_ATUALIZACAO_PENDENTE

    from ..models import Cidadao

    cidadao = (
        Cidadao.objects.select_related(
            'documentos',
            'endereco',
            'socioeconomico',
            'termo_responsabilidade',
        )
        .prefetch_related('documentos_anexados')
        .filter(pk=cidadao_id)
        .first()
    )
    if cidadao is None:
        return STATUS_ATUALIZACAO_PENDENTE

    return salvar_status_atualizacao_cidadao(cidadao)
