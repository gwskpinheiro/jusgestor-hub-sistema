from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.core.utils import incluir_atual
from apps.processos.models import Processo

from .models import LancamentoFinanceiro

DATA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
VALOR = forms.NumberInput(attrs={"min": "0.01", "step": "0.01"})


class LancamentoForm(forms.ModelForm):
    class Meta:
        model = LancamentoFinanceiro
        fields = ["tipo", "descricao", "valor", "vencimento", "cliente", "processo"]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 2}), "vencimento": DATA, "valor": VALOR}
        help_texts = {"cliente": "Opcional.", "processo": "Opcional. O cliente do processo é usado automaticamente."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        atual = self.instance if self.instance.pk else None
        self.fields["cliente"].queryset = incluir_atual(
            Cliente.objects.filter(arquivado=False), Cliente, atual and atual.cliente_id)
        self.fields["processo"].queryset = incluir_atual(
            Processo.objects.filter(arquivado=False).select_related("cliente"), Processo, atual and atual.processo_id)
        if atual and atual.cobrancas.exists():
            # Lançamento gerado por horas: tipo e vínculos refletem as horas cobradas.
            for campo in ("tipo", "cliente", "processo"):
                self.fields[campo].disabled = True
                self.fields[campo].help_text = "Definido pela conversão de horas."

    def clean_valor(self):
        valor = self.cleaned_data["valor"]
        if valor is None or valor <= 0:
            raise forms.ValidationError("Informe um valor positivo em reais.")
        return valor

    def clean(self):
        dados = super().clean()
        cliente, processo = dados.get("cliente"), dados.get("processo")
        if processo:
            if cliente and cliente.pk != processo.cliente_id:
                self.add_error("cliente", "O cliente deve ser o mesmo do processo selecionado.")
            else:
                dados["cliente"] = processo.cliente
        return dados


class QuitacaoForm(forms.Form):
    data_quitacao = forms.DateField(label="Data da quitação", widget=DATA)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.setdefault("data_quitacao", timezone.localdate())


class EscolhaProcessoForm(forms.Form):
    processo = forms.ModelChoiceField(
        label="Processo", queryset=Processo.objects.select_related("cliente").order_by("titulo"),
    )


class CobrancaHorasForm(forms.Form):
    """RN10: ADM seleciona as horas do processo e confirma o valor da cobrança."""

    registros = forms.ModelMultipleChoiceField(
        label="Registros de horas", queryset=None, widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Selecione ao menos um registro de horas."},
    )
    valor = forms.DecimalField(label="Valor confirmado (R$)", max_digits=12, decimal_places=2,
                               min_value=Decimal("0.01"), widget=VALOR)
    descricao = forms.CharField(label="Descrição", widget=forms.Textarea(attrs={"rows": 2}))
    vencimento = forms.DateField(label="Vencimento", widget=DATA)

    def __init__(self, *args, disponiveis, processo, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["registros"].queryset = disponiveis
        self.fields["registros"].label_from_instance = lambda r: (
            f"{r.data_atividade:%d/%m/%Y} · {r.usuario.nome} · {r.minutos // 60}h{r.minutos % 60:02d} · {r.atividade[:60]}"
        )
        self.initial.setdefault("descricao", f"Honorários por horas trabalhadas — {processo}")
