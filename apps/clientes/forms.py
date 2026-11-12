from django import forms

from .models import Cliente, so_digitos


class ClienteForm(forms.ModelForm):
    # Aceita o número formatado (até 18 caracteres); grava apenas os dígitos.
    cpf_cnpj = forms.CharField(label="CPF/CNPJ", max_length=18, required=False)

    class Meta:
        model = Cliente
        fields = ["nome", "cpf_cnpj", "email", "telefone", "endereco", "observacoes"]
        widgets = {
            "endereco": forms.Textarea(attrs={"rows": 2}),
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_cpf_cnpj(self):
        digitos = so_digitos(self.cleaned_data.get("cpf_cnpj"))
        if not digitos:
            return None
        if len(digitos) not in (11, 14):
            raise forms.ValidationError("Informe um CPF (11 dígitos) ou um CNPJ (14 dígitos).")
        return digitos
