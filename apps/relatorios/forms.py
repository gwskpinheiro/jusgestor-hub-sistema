"""Filtros dos relatórios (RF08). As opções respeitam as permissões do usuário."""
from django import forms

from apps.agenda.models import SituacaoCompromisso, TipoCompromisso
from apps.core.acesso import e_adm, processos_visiveis
from apps.financeiro.models import SituacaoLancamento, TipoLancamento
from apps.processos.models import SituacaoProcesso
from apps.usuarios.models import Perfil, Usuario

DATA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
TODAS = [("", "Todas")]
TODOS = [("", "Todos")]


class FiltroBase(forms.Form):
    de = forms.DateField(label="De", required=False, widget=DATA)
    ate = forms.DateField(label="Até", required=False, widget=DATA)
    rotulo_periodo = "Período"

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario

    def clean(self):
        dados = super().clean()
        if dados.get("de") and dados.get("ate") and dados["de"] > dados["ate"]:
            self.add_error("ate", "A data final deve ser igual ou posterior à inicial.")
        return dados


class FiltroProcessos(FiltroBase):
    rotulo_periodo = "Cadastro"
    situacao = forms.ChoiceField(label="Situação", choices=TODAS + SituacaoProcesso.choices, required=False)
    arquivados = forms.ChoiceField(
        label="Arquivados", required=False,
        choices=[("nao", "Não incluir"), ("sim", "Somente arquivados"), ("todos", "Incluir")],
    )
    responsavel = forms.ModelChoiceField(label="Responsável", queryset=Usuario.objects.none(), required=False,
                                         empty_label="Todos")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if e_adm(self.usuario):
            self.fields["responsavel"].queryset = Usuario.objects.filter(perfil__in=[Perfil.ADM, Perfil.ADV])
        else:
            del self.fields["responsavel"]


class FiltroAgenda(FiltroBase):
    situacao = forms.ChoiceField(label="Situação", choices=TODAS + SituacaoCompromisso.choices, required=False)
    tipo = forms.ChoiceField(label="Tipo", choices=TODOS + TipoCompromisso.choices, required=False)
    processo = forms.ModelChoiceField(label="Processo", queryset=None, required=False, empty_label="Todos")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["processo"].queryset = processos_visiveis(self.usuario).order_by("titulo")


class FiltroHoras(FiltroBase):
    processo = forms.ModelChoiceField(label="Processo", queryset=None, required=False, empty_label="Todos")
    usuario_filtro = forms.ModelChoiceField(label="Usuário", queryset=Usuario.objects.none(), required=False,
                                            empty_label="Toda a equipe")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["processo"].queryset = processos_visiveis(self.usuario).order_by("titulo")
        if e_adm(self.usuario):
            self.fields["usuario_filtro"].queryset = Usuario.objects.filter(perfil__in=[Perfil.ADM, Perfil.ADV])
        else:
            # RN09: ADV consulta apenas as próprias horas.
            del self.fields["usuario_filtro"]


class FiltroFinanceiro(FiltroBase):
    rotulo_periodo = "Vencimento"
    tipo = forms.ChoiceField(label="Tipo", choices=TODOS + TipoLancamento.choices, required=False)
    situacao = forms.ChoiceField(label="Situação", choices=TODAS + SituacaoLancamento.choices, required=False)
