from django import forms

from apps.clientes.models import Cliente
from apps.core.acesso import clientes_visiveis, e_adm
from apps.core.utils import incluir_atual
from apps.usuarios.models import Perfil, Usuario

from .models import Processo


class ProcessoForm(forms.ModelForm):
    class Meta:
        model = Processo
        fields = ["numero", "titulo", "cliente", "responsavel", "situacao", "descricao"]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 4})}
        help_texts = {"numero": "Opcional. Se informado, não pode se repetir no escritório."}

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        atual = self.instance if self.instance.pk else None

        # Cliente: somente clientes autorizados e não arquivados (mantém o atual na edição).
        clientes = clientes_visiveis(usuario).filter(arquivado=False)
        self.fields["cliente"].queryset = incluir_atual(clientes, Cliente, atual and atual.cliente_id)

        # RN01: responsável ADM ou ADV ativo.
        responsaveis = Usuario.objects.filter(ativo=True, perfil__in=[Perfil.ADM, Perfil.ADV])
        self.fields["responsavel"].queryset = incluir_atual(responsaveis, Usuario, atual and atual.responsavel_id)
        if not e_adm(usuario):
            # ADV não transfere a responsabilidade: no cadastro, ele é o responsável.
            self.fields["responsavel"].disabled = True
            if not atual:
                self.initial["responsavel"] = usuario.pk
                self.fields["responsavel"].queryset = Usuario.objects.filter(pk=usuario.pk)
            self.fields["responsavel"].help_text = "Somente o administrador altera o responsável."
