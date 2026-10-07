import hashlib
import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import FileExtensionValidator

User = get_user_model()


def documento_anexo_upload_to(instance, filename):
    extensao = filename.split('.')[-1].lower() if '.' in filename else 'bin'
    nome_base = instance.tipo_documento
    return (
        f'cidadaos/{instance.cidadao_id}/documentos/'
        f'{nome_base}_{uuid.uuid4().hex}.{extensao}'
    )


def documento_pdf_upload_to(instance, filename):
    extensao = filename.split('.')[-1].lower() if '.' in filename else 'pdf'
    return (
        f'cidadaos/{instance.id}/documentos_pdf/'
        f'documento_{uuid.uuid4().hex}.{extensao}'
    )

# --- CLASSE BASE PARA SINCRONISMO ---
class BaseSincronizacao(models.Model):
    """Herança para garantir UUID e controle de sincronismo em todas as tabelas"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Controle de Sincronismo
    sincronizado = models.BooleanField(default=False)
    status_sincronizacao = models.CharField(
        max_length=20,
        choices=[
            ('PENDENTE', 'Pendente'),
            ('SINCRONIZADO', 'Sincronizado'),
            ('ERRO', 'Erro'),
        ],
        default='PENDENTE'
    )
    sincronizado_em = models.DateTimeField(null=True, blank=True)
    
    # Auditoria
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# --- MODELOS DO SISTEMA ---

class KeycloakUserData(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='keycloak_data')
    keycloak_username = models.CharField(max_length=150, blank=True)
    roles = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.keycloak_username or self.user.username


class Cidadao(BaseSincronizacao):
    STATUS_ATUALIZACAO_PENDENTE = 'PENDENTE'
    STATUS_ATUALIZACAO_ATUALIZADO = 'ATUALIZADO'
    STATUS_ATUALIZACAO_DESATUALIZADO = 'DESATUALIZADO'
    STATUS_ATUALIZACAO_CHOICES = [
        (STATUS_ATUALIZACAO_PENDENTE, 'Pendente'),
        (STATUS_ATUALIZACAO_ATUALIZADO, 'Atualizado'),
        (STATUS_ATUALIZACAO_DESATUALIZADO, 'Desatualizado'),
    ]

    ESTADO_CIVIL_CHOICES = [
        ('SOLTEIRO', 'Solteiro'),
        ('CASADO', 'Casado'),
        ('DIVORCIADO', 'Divorciado'),
        ('VIUVO', 'Viúvo'),
        ('UNIAO_ESTAVEL', 'União estável'),
        ('NAO_INFORMADO', 'Não informado'),
    ]

    nome = models.CharField(max_length=200, db_index=True)
    nis = models.CharField(max_length=20, unique=True, blank=True, null=True)
    data_nascimento = models.DateField(null=True, blank=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(unique=True, blank=True, null=True)
    
    naturalidade = models.CharField(max_length=100, blank=True, null=True)
    ocupacao = models.CharField(max_length=100, blank=True, default='')
    possui_carteira_trabalho = models.BooleanField(default=False)
    encaminhamentos = models.TextField(blank=True, default='')
    escolaridade = models.CharField(max_length=100, blank=True, null=True)
    identidade_genero = models.CharField(max_length=50, blank=True, null=True)
    cor = models.CharField(max_length=50, blank=True, null=True)
    possui_deficiencia = models.BooleanField(default=False)
    estado_civil = models.CharField(max_length=20, choices=ESTADO_CIVIL_CHOICES, blank=True, null=True)
    tempo_residencia = models.CharField(max_length=100, blank=True, default='', verbose_name='Tempo que reside em Tefé')
    autorizacao_uso_imagem = models.BooleanField(default=False)
    autorizacao_uso_imagem_aceite_em = models.DateTimeField(null=True, blank=True)
    autorizacao_uso_imagem_responsavel = models.CharField(max_length=200, blank=True, null=True)
    documento_pdf = models.FileField(
        upload_to=documento_pdf_upload_to,
        validators=[FileExtensionValidator(['pdf'])],
        blank=True,
        null=True,
    )
    documento_pdf_nome_arquivo = models.CharField(
        max_length=255,
        blank=True,
        default='',
    )
    status_atualizacao = models.CharField(
        max_length=20,
        choices=STATUS_ATUALIZACAO_CHOICES,
        default=STATUS_ATUALIZACAO_PENDENTE,
        db_index=True,
    )
    atualizado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cidadaos_atualizados',
    )

    class Meta:
        db_table = 'api_cidadao'
        verbose_name = 'Cidadão'
        indexes = [
            models.Index(fields=['atualizado_em'], name='api_cidadao_atualizado_idx'),
        ]

    def __str__(self):
        return self.nome


class Documento(BaseSincronizacao):
    cidadao = models.OneToOneField(Cidadao, on_delete=models.CASCADE, related_name='documentos')
    cpf = models.CharField(max_length=14, unique=True, blank=True, null=True)
    rg = models.CharField(max_length=20, blank=True, null=True)
    rg_orgao = models.CharField(max_length=20, blank=True, null=True)
    rg_uf = models.CharField(max_length=2, blank=True, null=True)
    carteira_trabalho = models.CharField(max_length=50, blank=True, null=True)
    inscricao_eleitoral = models.CharField(max_length=30, blank=True, null=True)
    zona = models.CharField(max_length=10, blank=True, null=True)
    secao = models.CharField(max_length=10, blank=True, null=True)

    class Meta:
        db_table = 'api_documentos'


class DocumentoAnexo(BaseSincronizacao):
    TIPO_RG = 'rg'
    TIPO_RG_FRENTE = 'rg_frente'
    TIPO_RG_VERSO = 'rg_verso'
    TIPO_CPF = 'cpf'
    TIPO_CERTIDAO_NASCIMENTO = 'certidao_nascimento'
    TIPO_CERTIDAO_CASAMENTO = 'certidao_casamento'
    TIPO_QUITACAO_ELEITORAL = 'quitacao_eleitoral'
    TIPO_COMPROVANTE_RESIDENCIA = 'comprovante_residencia'
    TIPO_FOTO_RESIDENCIA = 'foto_residencia'
    TIPO_FOTO_ATO_ATUALIZACAO = 'foto_ato_atualizacao'

    TIPOS_CHOICES = [
        (TIPO_RG_FRENTE, 'RG - Frente'),
        (TIPO_RG_VERSO, 'RG - Verso'),
        (TIPO_CPF, 'CPF'),
        (TIPO_CERTIDAO_NASCIMENTO, 'Certidão de Nascimento'),
        (TIPO_CERTIDAO_CASAMENTO, 'Certidão de Casamento'),
        (TIPO_QUITACAO_ELEITORAL, 'Quitação Eleitoral'),
        (TIPO_COMPROVANTE_RESIDENCIA, 'Comprovante de residência'),
        (TIPO_FOTO_RESIDENCIA, 'Foto da residência'),
        (TIPO_FOTO_ATO_ATUALIZACAO, 'Foto do ato da atualização'),
    ]

    cidadao = models.ForeignKey(
        Cidadao,
        on_delete=models.CASCADE,
        related_name='documentos_anexados',
    )
    tipo_documento = models.CharField(max_length=50, choices=TIPOS_CHOICES)
    arquivo = models.FileField(
        upload_to=documento_anexo_upload_to,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
        blank=True,
        null=True,
    )
    nome_arquivo = models.CharField(max_length=255)
    extensao = models.CharField(max_length=10)
    tamanho_bytes = models.PositiveBigIntegerField(default=0)
    data_envio = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=30, default='ENVIADO')
    sem_documento_no_momento = models.BooleanField(default=False)

    class Meta:
        db_table = 'api_documentos_anexos'
        constraints = [
            models.UniqueConstraint(
                fields=['cidadao', 'tipo_documento'],
                name='uq_documento_anexo_cidadao_tipo',
            ),
        ]

    def __str__(self):
        return f'{self.cidadao} - {self.tipo_documento}'

    def delete(self, using=None, keep_parents=False):
        storage = self.arquivo.storage if self.arquivo else None
        arquivo_nome = self.arquivo.name if self.arquivo else ''
        super().delete(using=using, keep_parents=keep_parents)
        if storage and arquivo_nome:
            try:
                storage.delete(arquivo_nome)
            except Exception:
                pass


class Endereco(BaseSincronizacao):
    TIPO_LOCALIZACAO_CHOICES = [
        ('URBANO', 'Urbano'),
        ('RURAL_DISTRITO', 'Rural/Distrito'),
    ]
    SITUACAO_CHOICES = [
        ('PROPRIA', 'Própria'),
        ('ALUGADA', 'Alugada'),
        ('CEDIDA', 'Cedida'),
        ('TEMPORARIA', 'Temporária'),
        ('NAO_INFORMADO', 'Não informado'),
    ]
    ABASTECIMENTO_AGUA_CHOICES = [
        ('REDE_PUBLICA', 'Rede pública'),
        ('POCO', 'Poço'),
        ('NASCENTE', 'Nascente'),
        ('CISTERNA', 'Cisterna'),
        ('CACIMBA', 'Cacimba'),
        ('OUTRO', 'Outro'),
        ('NAO_INFORMADO', 'Não informado'),
    ]

    cidadao = models.OneToOneField(Cidadao, on_delete=models.CASCADE, related_name='endereco')
    logradouro = models.CharField(max_length=200)
    tipo_localizacao = models.CharField(
        max_length=20,
        choices=TIPO_LOCALIZACAO_CHOICES,
        blank=True,
        null=True,
    )
    bairro = models.CharField(max_length=100, blank=True, default='')
    distrito = models.CharField(max_length=100, blank=True, null=True)
    comunidade_localidade = models.CharField(max_length=150, blank=True, null=True)
    numero = models.CharField(max_length=20, blank=True, null=True)
    cep = models.CharField(max_length=10, blank=True, null=True)
    complemento = models.CharField(max_length=100, blank=True, null=True)
    
    situacao_imovel = models.CharField(max_length=20, choices=SITUACAO_CHOICES, blank=True, null=True)
    valor_aluguel = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    material_parede = models.CharField(max_length=50, blank=True, null=True)
    qtd_comodos = models.IntegerField(default=1, null=True, blank=True)
    
    possui_luz = models.BooleanField(null=True, blank=True)
    possui_asfalto = models.BooleanField(null=True, blank=True)
    possui_lixo = models.BooleanField(null=True, blank=True)
    abastecimento_agua = models.CharField(
        max_length=20,
        choices=ABASTECIMENTO_AGUA_CHOICES,
        blank=True,
        null=True,
    )
    abastecimento_agua_outro = models.CharField(max_length=100, blank=True, null=True)
    possui_saneamento = models.BooleanField(null=True, blank=True)

    # --- Situação habitacional (SEMASC) ---
    iluminacao_publica = models.BooleanField(null=True, blank=True)
    risco_inundacao = models.BooleanField(default=False)
    risco_enchente = models.BooleanField(default=False)
    risco_deslizamento = models.BooleanField(default=False)
    possui_doc_posse = models.BooleanField(default=False)
    doc_posse_descricao = models.CharField(max_length=200, blank=True, default='')
    motivo_terceiros = models.CharField(max_length=300, blank=True, default='')

    # --- Geocodificação / Mapa de calor ---
    GEO_STATUS_PENDENTE = 'PENDENTE'
    GEO_STATUS_OK = 'OK'
    GEO_STATUS_NAO_ENCONTRADO = 'NAO_ENCONTRADO'
    GEO_STATUS_ERRO = 'ERRO'
    GEOCODIFICACAO_STATUS_CHOICES = [
        (GEO_STATUS_PENDENTE, 'Pendente'),
        (GEO_STATUS_OK, 'Geocodificado'),
        (GEO_STATUS_NAO_ENCONTRADO, 'Não encontrado'),
        (GEO_STATUS_ERRO, 'Erro'),
    ]

    PRECISAO_EXATO = 'ENDERECO_EXATO'
    PRECISAO_RUA = 'RUA'
    PRECISAO_LOCALIDADE = 'LOCALIDADE'
    PRECISAO_MANUAL = 'MANUAL'
    PRECISAO_CHOICES = [
        (PRECISAO_EXATO, 'Endereço exato'),
        (PRECISAO_RUA, 'Rua'),
        (PRECISAO_LOCALIDADE, 'Localidade'),
        (PRECISAO_MANUAL, 'Manual'),
    ]

    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    endereco_geocodificado = models.CharField(max_length=300, blank=True, default='')
    geocodificacao_status = models.CharField(
        max_length=20,
        choices=GEOCODIFICACAO_STATUS_CHOICES,
        default=GEO_STATUS_PENDENTE,
        db_index=True,
    )
    geocodificacao_erro = models.TextField(blank=True, default='')
    geocodificado_em = models.DateTimeField(null=True, blank=True)
    precisao_geocodificacao = models.CharField(
        max_length=20,
        choices=PRECISAO_CHOICES,
        null=True,
        blank=True,
    )
    # Assinatura dos campos de endereço — detecta alteração para reprocessar.
    endereco_hash = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        db_table = 'api_habitacao'

    def _assinatura_endereco(self):
        partes = [
            self.logradouro,
            self.numero,
            self.bairro,
            self.distrito,
            self.comunidade_localidade,
        ]
        base = '|'.join((parte or '').strip().lower() for parte in partes)
        return hashlib.sha256(base.encode('utf-8')).hexdigest()

    @property
    def tem_endereco_geocodificavel(self):
        return bool(
            (self.logradouro or '').strip()
            or (self.bairro or '').strip()
            or (self.comunidade_localidade or '').strip()
            or (self.distrito or '').strip()
        )

    def save(self, *args, **kwargs):
        novo_hash = self._assinatura_endereco()
        # Coordenadas manuais nunca são descartadas automaticamente.
        if self.precisao_geocodificacao != self.PRECISAO_MANUAL and self.endereco_hash != novo_hash:
            self.latitude = None
            self.longitude = None
            self.endereco_geocodificado = ''
            self.geocodificacao_erro = ''
            self.geocodificado_em = None
            self.precisao_geocodificacao = None
            self.geocodificacao_status = (
                self.GEO_STATUS_PENDENTE
                if self.tem_endereco_geocodificavel
                else self.GEO_STATUS_NAO_ENCONTRADO
            )
        self.endereco_hash = novo_hash
        super().save(*args, **kwargs)


class FamiliaMembro(BaseSincronizacao):
    cidadao_titular = models.ForeignKey(Cidadao, on_delete=models.CASCADE, related_name='membros_familia')
    local_id = models.CharField(max_length=64, blank=True, default='')
    nome_membro = models.CharField(max_length=200)
    parentesco = models.CharField(max_length=50)
    cpf_membro = models.CharField(max_length=14, blank=True, null=True)
    nao_possui_cpf = models.BooleanField(default=False)
    data_nascimento = models.DateField(null=True, blank=True)
    sexo = models.CharField(max_length=20, blank=True, null=True)
    escolaridade = models.CharField(max_length=100, blank=True, null=True)
    ocupacao = models.CharField(max_length=100, blank=True, null=True)
    escola_em_que_estuda = models.CharField(max_length=200, blank=True, null=True)
    gestante = models.BooleanField(default=False)
    possui_deficiencia = models.BooleanField(default=False)
    qual_deficiencia = models.CharField(max_length=200, blank=True, null=True)
    
    # Saúde e Social Individualizado (como discutido)
    possui_cartao_sus = models.BooleanField(default=True)
    possui_doenca_grave = models.BooleanField(default=False)
    descricao_doenca = models.TextField(blank=True, null=True)
    uso_substancia_ilicita = models.BooleanField(default=False)
    descricao_substancia = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'api_familia_membros'


class Escola(BaseSincronizacao):
    codigo = models.CharField(max_length=20, unique=True, blank=True, null=True)
    nome = models.CharField(max_length=200, unique=True)
    tipo = models.CharField(max_length=50, blank=True, null=True)
    zona = models.CharField(max_length=20, blank=True, null=True)

    class Meta:
        db_table = 'api_escola'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class LocalTefe(BaseSincronizacao):
    TIPO_BAIRRO = 'BAIRRO'
    TIPO_DISTRITO = 'DISTRITO'
    TIPO_COMUNIDADE = 'COMUNIDADE'

    TIPO_CHOICES = [
        (TIPO_BAIRRO, 'Bairro'),
        (TIPO_DISTRITO, 'Distrito'),
        (TIPO_COMUNIDADE, 'Comunidade'),
    ]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    nome = models.CharField(max_length=200)
    ativo = models.BooleanField(default=True)
    ordem = models.IntegerField(default=0)

    class Meta:
        db_table = 'api_locais_tefe'
        ordering = ['ordem', 'nome']
        constraints = [
            models.UniqueConstraint(
                fields=['tipo', 'nome'],
                name='uq_local_tefe_tipo_nome',
            ),
        ]

    def __str__(self):
        return f'{self.tipo} - {self.nome}'


class Localidade(BaseSincronizacao):
    TIPO_BAIRRO = 'BAIRRO'
    TIPO_COMUNIDADE = 'COMUNIDADE'
    TIPO_DISTRITO = 'DISTRITO'

    TIPO_CHOICES = [
        (TIPO_BAIRRO, 'Bairro'),
        (TIPO_COMUNIDADE, 'Comunidade'),
        (TIPO_DISTRITO, 'Distrito'),
    ]

    nome = models.CharField(max_length=200, unique=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    criada_automaticamente = models.BooleanField(default=False)

    class Meta:
        db_table = 'api_localidades'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Rua(BaseSincronizacao):
    nome = models.CharField(max_length=200)
    localidade = models.ForeignKey(
        Localidade,
        on_delete=models.CASCADE,
        related_name='ruas',
    )
    criada_automaticamente = models.BooleanField(default=False)

    class Meta:
        db_table = 'api_ruas'
        ordering = ['nome']
        constraints = [
            models.UniqueConstraint(
                fields=['localidade', 'nome'],
                name='uq_rua_localidade_nome',
            ),
        ]

    def __str__(self):
        return f'{self.nome} - {self.localidade.nome}'


class Socioeconomico(BaseSincronizacao):
    cidadao = models.OneToOneField(Cidadao, on_delete=models.CASCADE, related_name='socioeconomico')
    renda_total = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    faixa_renda = models.CharField(max_length=20, blank=True, default='')
    precedencia_rendimento = models.TextField(blank=True)
    pessoas_com_rendimento = models.IntegerField(default=1)
    recebe_beneficio = models.BooleanField(default=False)
    beneficio_nome = models.CharField(max_length=150, blank=True, null=True)
    beneficio_tipo = models.CharField(max_length=100, blank=True, null=True)
    beneficio_valor = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    beneficios_recebidos = models.JSONField(default=list, blank=True)
    quantidade_pessoas_residencia = models.IntegerField(default=0)
    quantidade_pessoas_estudando = models.IntegerField(default=0)
    quantidade_criancas = models.IntegerField(default=0)
    quantidade_adolescentes = models.IntegerField(default=0)
    quantidade_adultos = models.IntegerField(default=0)
    quantidade_idosos = models.IntegerField(default=0)
    ha_gestante = models.BooleanField(default=False)
    ha_pessoa_com_deficiencia = models.BooleanField(default=False)
    qual_deficiencia = models.CharField(max_length=200, blank=True, null=True)
    utiliza_servico_social = models.BooleanField(default=False)
    servicos_sociais = models.JSONField(default=list, blank=True)
    pretende_voltar_estudar = models.BooleanField(default=False)
    possui_medida_protetiva = models.BooleanField(default=False)
    violencia_domestica = models.BooleanField(default=False)
    eh_ribeirinho = models.BooleanField(default=False)
    cidadao_estava_em_casa = models.BooleanField(default=False)
    ja_foi_visitado = models.BooleanField(default=False)
    mais_de_um_nucleo = models.BooleanField(default=False)
    documentacao_completa_grupo = models.BooleanField(default=True)
    observacoes_gerais = models.TextField(blank=True)

    class Meta:
        db_table = 'api_socioeconomico'


class TermoResponsabilidade(BaseSincronizacao):
    cidadao = models.OneToOneField(
        Cidadao,
        on_delete=models.CASCADE,
        related_name='termo_responsabilidade',
    )
    nome_responsavel = models.CharField(max_length=200, blank=True, null=True)
    funcao = models.CharField(max_length=150, blank=True, default='')
    local_termo = models.CharField(max_length=200, blank=True, null=True)
    data_termo = models.CharField(max_length=20, blank=True, null=True)
    hora_termo = models.CharField(max_length=10, blank=True, null=True)

    class Meta:
        db_table = 'api_termo_responsabilidade'


class Beneficio(BaseSincronizacao):
    nome = models.CharField(max_length=150, unique=True)
    descricao = models.TextField(blank=True, default='')
    icone = models.CharField(max_length=50, blank=True, default='VOLUNTEER_ACTIVISM')
    ativo = models.BooleanField(default=True)
    atualizado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='beneficios_atualizados',
    )

    class Meta:
        db_table = 'api_beneficio'
        verbose_name = 'Benefício'
        indexes = [
            models.Index(fields=['atualizado_em'], name='api_beneficio_atualiz_idx'),
        ]

    def __str__(self):
        return self.nome


class Beneficiario(BaseSincronizacao):
    STATUS_CHOICES = [
        ('EM_ANALISE', 'Em análise'),
        ('APROVADO', 'Aprovado'),
        ('REPROVADO', 'Reprovado'),
    ]

    cidadao = models.ForeignKey(Cidadao, on_delete=models.CASCADE, related_name='beneficios_recebidos')
    beneficio = models.ForeignKey(Beneficio, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='EM_ANALISE',
        db_index=True,
    )
    situacao_cadastro = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='EM_ANALISE',
        db_index=True,
    )
    valor_recebido = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    data_solicitacao = models.DateField(auto_now_add=True)
    atualizado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='beneficiarios_atualizados',
    )

    class Meta:
        unique_together = ('cidadao', 'beneficio')
        indexes = [
            models.Index(fields=['beneficio', 'status']),
            models.Index(fields=['cidadao', 'status']),
            models.Index(fields=['atualizado_em'], name='api_benefic_atualiz_0102e4_idx'),
        ]

    def save(self, *args, **kwargs):
        # Mantém compatibilidade com bancos que ainda exigem essa coluna.
        self.situacao_cadastro = self.status or 'EM_ANALISE'
        return super().save(*args, **kwargs)


class LocalidadeBeneficiario(models.Model):
    """Coordenada curada por localidade (bairro/comunidade/distrito) para o
    mapa de calor. Cada beneficiário herda a coordenada da sua localidade,
    em vez de geocodificar endereço por endereço (que erra com os nomes
    informais de Tefé)."""

    FONTE_PENDENTE = 'PENDENTE'
    FONTE_GOOGLE = 'GOOGLE'
    FONTE_MANUAL = 'MANUAL'
    FONTE_CHOICES = [
        (FONTE_PENDENTE, 'Pendente'),
        (FONTE_GOOGLE, 'Google (revisar)'),
        (FONTE_MANUAL, 'Manual'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nome = models.CharField(max_length=150, unique=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    fonte = models.CharField(max_length=20, choices=FONTE_CHOICES, default=FONTE_PENDENTE)
    # Diagnóstico do geocode automático (Google), só para apoiar a revisão.
    google_formatted = models.CharField(max_length=300, blank=True, default='')
    google_partial = models.BooleanField(default=False)
    dentro_de_tefe = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'api_localidade_beneficiario'
        ordering = ['nome']

    def __str__(self):
        return self.nome
