from django import forms

from apps.core.acesso import processos_visiveis
from apps.core.utils import incluir_atual
from apps.processos.models import Processo

from .models import RegistroHora


class RegistroHoraForm(forms.ModelForm):
    class Meta:
        model = RegistroHora
        fields = ["processo", "data_atividade", "minutos", "atividade"]
        widgets = {
            "data_atividade": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "minutos": forms.NumberInput(attrs={"min": 1, "step": 1}),
            "atividade": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {"minutos": "Duração em minutos (ex.: 90 para 1h30)."}

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        atual = self.instance if self.instance.pk else None
        processos = processos_visiveis(usuario).filter(arquivado=False).select_related("cliente")
        self.fields["processo"].queryset = incluir_atual(processos, Processo, atual and atual.processo_id)
        self.fields["minutos"].min_value = 1

    def clean_minutos(self):
        minutos = self.cleaned_data["minutos"]
        if minutos is None or minutos <= 0:
            raise forms.ValidationError("Informe uma quantidade positiva de minutos.")
        return minutos
