"""Largura do conteúdo e contraste dos componentes (melhorias visuais)."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ESTATICOS = Path(settings.BASE_DIR) / "static"


def css():
    return (ESTATICOS / "css" / "app.css").read_text(encoding="utf-8")


class LayoutContrasteTests(SimpleTestCase):
    def test_conteudo_sem_limite_de_1200px(self):
        regra = re.search(r"\.conteudo\s*\{[^}]*\}", css()).group(0)
        self.assertNotIn("max-width", regra)
        self.assertIn("margin-left: var(--largura-menu)", regra)

    def test_bordas_de_campos_com_contraste_minimo(self):
        def luminancia(hexa):
            canais = [int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            canais = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canais]
            return 0.2126 * canais[0] + 0.7152 * canais[1] + 0.0722 * canais[2]

        def contraste(a, b):
            la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
            return (la + 0.05) / (lb + 0.05)

        variaveis = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", css()))
        self.assertGreaterEqual(contraste(variaveis["cor-borda-campo"], "#ffffff"), 3.0)   # WCAG 1.4.11
        self.assertGreaterEqual(contraste(variaveis["cor-foco"], "#ffffff"), 3.0)
        self.assertGreaterEqual(contraste(variaveis["cor-texto-rotulo"], variaveis["cor-cabecalho-tabela"]), 4.5)
        for seletor in (".campo input, .campo select, .campo textarea {", ".filtros input, .filtros select {"):
            bloco = css().split(seletor, 1)[1].split("}", 1)[0]
            self.assertIn("var(--cor-borda-campo)", bloco)
