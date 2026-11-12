from django import forms
from django.db import transaction

from apps.core.acesso import e_adm, processos_visiveis
from apps.core.utils import incluir_atual
from apps.processos.models import Processo
from apps.usuarios.models import Usuario

from .models import Compromisso, ParticipanteCompromisso

FORMATO_DATA_HORA = "%Y-%m-%dT%H:%M"


class CampoDataHora(forms.DateTimeField):
    widget = forms.DateTimeInput(attrs={"type": "datetime-local"}, format=FORMATO_DATA_HORA)

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("input_formats", [FORMATO_DATA_HORA, "%Y-%m-%d %H:%M"])
        super().__init__(*args, **kwargs)


class CompromissoForm(forms.ModelForm):
    inicio = CampoDataHora(label="Data e hora")
    fim = CampoDataHora(label="Término", required=False)
    participantes = forms.ModelMultipleChoiceField(
        label="Participantes", queryset=Usuario.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Participar não concede acesso ao processo vinculado.",
    )

    class Meta:
        model = Compromisso
        fields = ["titulo", "tipo", "inicio", "fim", "situacao", "responsavel", "participantes", "processo", "descricao"]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        atual = self.instance if self.instance.pk else None
        ativos = Usuario.objects.filter(ativo=True)
        self.fields["responsavel"].queryset = incluir_atual(ativos, Usuario, atual and atual.responsavel_id)
        self.fields["participantes"].queryset = ativos
        processos = processos_visiveis(usuario).filter(arquivado=False)
        self.fields["processo"].queryset = incluir_atual(processos, Processo, atual and atual.processo_id)
        self.fields["processo"].help_text = "Opcional."
        if atual:
            self.initial["participantes"] = list(atual.participantes.values_list("usuario_id", flat=True))
        else:
            self.initial.setdefault("responsavel", usuario.pk)

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("inicio"), dados.get("fim")
        if inicio and fim and fim < inicio:
            self.add_error("fim", "O término deve ser posterior ao início.")
        # Quem não é ADM precisa continuar com acesso ao registro após salvar.
        responsavel = dados.get("responsavel")
        if responsavel and not e_adm(self.usuario):
            participa = self.usuario in (dados.get("participantes") or [])
            processo = dados.get("processo")
            ve_processo = processo is not None and processos_visiveis(self.usuario).filter(pk=processo.pk).exists()
            if responsavel != self.usuario and not participa and not ve_processo:
                raise forms.ValidationError(
                    "Você precisa ser o responsável ou participante deste compromisso para continuar com acesso a ele."
                )
        return dados

    def save(self, commit=True):
        with transaction.atomic():
            compromisso = super().save(commit=True)
            novos = set(u.pk for u in self.cleaned_data.get("participantes") or [])
            existentes = set(compromisso.participantes.values_list("usuario_id", flat=True))
            ParticipanteCompromisso.objects.filter(
                compromisso=compromisso, usuario_id__in=existentes - novos
            ).delete()
            ParticipanteCompromisso.objects.bulk_create(
                [ParticipanteCompromisso(compromisso=compromisso, usuario_id=pk) for pk in novos - existentes]
            )
        return compromisso
