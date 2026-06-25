from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Cidadao, Documento, DocumentoAnexo, Endereco, Socioeconomico, TermoResponsabilidade
from .services.status_atualizacao_service import (
    recalcular_status_atualizacao_por_id,
    salvar_status_atualizacao_cidadao,
)


@receiver(post_save, sender=Cidadao)
def atualizar_status_cidadao_base(sender, instance, **kwargs):
    salvar_status_atualizacao_cidadao(instance)


@receiver(post_save, sender=Documento)
def atualizar_status_cidadao_documentos(sender, instance, **kwargs):
    salvar_status_atualizacao_cidadao(instance.cidadao)


@receiver(post_delete, sender=Documento)
def atualizar_status_cidadao_documentos_delete(sender, instance, **kwargs):
    recalcular_status_atualizacao_por_id(instance.cidadao_id)


@receiver(post_save, sender=Endereco)
def atualizar_status_cidadao_endereco(sender, instance, **kwargs):
    salvar_status_atualizacao_cidadao(instance.cidadao)


@receiver(post_delete, sender=Endereco)
def atualizar_status_cidadao_endereco_delete(sender, instance, **kwargs):
    recalcular_status_atualizacao_por_id(instance.cidadao_id)


@receiver(post_save, sender=Socioeconomico)
def atualizar_status_cidadao_socioeconomico(sender, instance, **kwargs):
    salvar_status_atualizacao_cidadao(instance.cidadao)


@receiver(post_delete, sender=Socioeconomico)
def atualizar_status_cidadao_socioeconomico_delete(sender, instance, **kwargs):
    recalcular_status_atualizacao_por_id(instance.cidadao_id)


@receiver(post_save, sender=TermoResponsabilidade)
def atualizar_status_cidadao_termo(sender, instance, **kwargs):
    salvar_status_atualizacao_cidadao(instance.cidadao)


@receiver(post_delete, sender=TermoResponsabilidade)
def atualizar_status_cidadao_termo_delete(sender, instance, **kwargs):
    recalcular_status_atualizacao_por_id(instance.cidadao_id)


@receiver(post_save, sender=DocumentoAnexo)
def atualizar_status_cidadao_documento_anexo(sender, instance, **kwargs):
    salvar_status_atualizacao_cidadao(instance.cidadao)


@receiver(post_delete, sender=DocumentoAnexo)
def atualizar_status_cidadao_documento_anexo_delete(sender, instance, **kwargs):
    recalcular_status_atualizacao_por_id(instance.cidadao_id)
