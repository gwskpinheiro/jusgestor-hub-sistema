from django import forms

from apps.core.acesso import clientes_visiveis, processos_visiveis

from .armazenamento import validar_arquivo
from .models import Documento

AJUDA_ARQUIVO = "PDF, DOCX, PNG ou JPEG, até 10 MiB."
ACEITOS = ".pdf,.docx,.png,.jpg,.jpeg"


class CampoArquivo(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label", "Arquivo")
        kwargs.setdefault("help_text", AJUDA_ARQUIVO)
        kwargs.setdefault("widget", forms.ClearableFileInput(attrs={"accept": ACEITOS}))
        super().__init__(*args, **kwargs)

    def clean(self, *args, **kwargs):
        arquivo = super().clean(*args, **kwargs)
        if arquivo:
            validar_arquivo(arquivo)
        return arquivo


class DocumentoForm(forms.ModelForm):
    arquivo = CampoArquivo()

    class Meta:
        model = Documento
        fields = ["titulo", "cliente", "processo", "descricao", "arquivo"]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 3})}
        help_texts = {
            "cliente": "Informe o cliente, o processo ou ambos.",
            "processo": "Documentos de processo só são vistos por quem acessa o processo.",
        }

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente"].queryset = clientes_visiveis(usuario).filter(arquivado=False)
        self.fields["processo"].queryset = processos_visiveis(usuario).filter(arquivado=False).select_related("cliente")

    def clean(self):
        dados = super().clean()
        cliente, processo = dados.get("cliente"), dados.get("processo")
        if not cliente and not processo and not self.errors.get("cliente") and not self.errors.get("processo"):
            raise forms.ValidationError("Vincule o documento a um cliente ou a um processo.")
        if processo:
            if cliente and cliente.pk != processo.cliente_id:
                self.add_error("cliente", "O cliente deve ser o mesmo do processo selecionado.")
            else:
                dados["cliente"] = processo.cliente
                self.instance.cliente = processo.cliente
        return dados


class DocumentoEdicaoForm(forms.ModelForm):
    """Edita título e descrição; os vínculos e versões são preservados."""

    class Meta:
        model = Documento
        fields = ["titulo", "descricao"]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 3})}


class NovaVersaoForm(forms.Form):
    arquivo = CampoArquivo(label="Nova versão")
