from django import forms

from apps.clientes.models import Cliente
from apps.processos.models import Processo

from .models import Usuario, UsuarioManager


class UsuarioForm(forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ["nome", "email", "perfil", "ativo"]
        help_texts = {"ativo": "Contas inativas não entram no sistema. Nenhuma conta é excluída."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            # Contas novas nascem ativas, com senha temporária gerada pelo sistema.
            del self.fields["ativo"]

    def clean_email(self):
        # Gravado em minúsculas; a unicidade é verificada no mesmo formato.
        return UsuarioManager.normalize_email(self.cleaned_data["email"])


class AcessosForm(forms.Form):
    clientes = forms.ModelMultipleChoiceField(
        label="Clientes autorizados", queryset=Cliente.objects.order_by("arquivado", "nome"),
        required=False, widget=forms.CheckboxSelectMultiple,
    )
    processos = forms.ModelMultipleChoiceField(
        label="Processos autorizados", queryset=Processo.objects.select_related("cliente").order_by("arquivado", "titulo"),
        required=False, widget=forms.CheckboxSelectMultiple,
        help_text="Acesso ao cliente não libera automaticamente os processos dele.",
    )
