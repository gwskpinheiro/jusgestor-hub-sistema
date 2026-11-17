"""Modo escuro: alternância, persistência no navegador e contraste dos tokens."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

from apps.core.tests import fabrica as f

ESTATICOS = Path(settings.BASE_DIR) / "static"
CHAVE = "jusgestor-tema"


def css():
    return (ESTATICOS / "css" / "app.css").read_text(encoding="utf-8")


def _tokens(bloco):
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", bloco))


def tokens_claros():
    return _tokens(re.search(r":root\s*\{(.*?)\n\}", css(), re.S).group(1))


def bloco_escuro():
    return re.search(r'@media screen\s*\{\s*html\[data-tema="escuro"\]\s*\{(.*?)\n  \}', css(), re.S).group(1)


def tokens_escuros():
    return {**tokens_claros(), **_tokens(bloco_escuro())}


def contraste(a, b):
    def luminancia(hexa):
        canais = [int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        canais = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canais]
        return 0.2126 * canais[0] + 0.7152 * canais[1] + 0.0722 * canais[2]

    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# Texto sobre fundo: mínimo 4,5:1 (WCAG 1.4.3) nos dois temas.
PARES_DE_TEXTO = [
    ("cor-texto", "cor-fundo"), ("cor-texto", "cor-superficie"), ("cor-texto", "cor-campo"),
    ("cor-texto-suave", "cor-superficie"), ("cor-texto-suave", "cor-fundo"),
    ("cor-texto-suave", "cor-neutro-fundo"), ("cor-texto-suave", "cor-campo-desabilitado"),
    ("cor-texto-rotulo", "cor-cabecalho-tabela"), ("cor-texto-rotulo", "cor-neutro-fundo"),
    ("cor-link", "cor-superficie"), ("cor-link", "cor-fundo"), ("cor-acento", "cor-superficie"),
    ("cor-texto-botao", "cor-primaria"), ("cor-texto-botao", "cor-primaria-hover"),
    ("cor-texto-botao", "cor-perigo-cheio"), ("cor-erro-texto", "cor-superficie"),
    ("cor-sucesso-texto", "cor-sucesso-fundo"), ("cor-alerta-texto", "cor-alerta-fundo"),
    ("cor-erro-texto", "cor-erro-fundo"), ("cor-info-texto", "cor-info-fundo"),
    ("cor-neutro-texto", "cor-neutro-fundo"), ("cor-menu-texto", "cor-menu"),
    ("cor-texto-botao", "cor-menu-ativo"),
    ("tipo-prazo-texto", "tipo-prazo-fundo"), ("tipo-tarefa-texto", "tipo-tarefa-fundo"),
    ("tipo-compromisso-texto", "tipo-compromisso-fundo"),
    ("cor-texto", "tipo-prazo-fundo"), ("cor-texto", "tipo-tarefa-fundo"), ("cor-texto", "tipo-compromisso-fundo"),
    ("cor-texto", "cor-info-fundo"), ("cor-texto", "cor-fundo-alternativo"),
]
# Bordas de campos, foco e marcadores de tipo: mínimo 3:1 (WCAG 1.4.11).
PARES_GRAFICOS = [
    ("cor-borda-campo", "cor-campo"), ("cor-foco", "cor-fundo"), ("cor-foco", "cor-superficie"),
    ("tipo-prazo-acento", "cor-superficie"), ("tipo-tarefa-acento", "cor-superficie"),
    ("tipo-compromisso-acento", "cor-superficie"),
]


class TokensDoTemaTests(SimpleTestCase):
    def test_escuro_so_redefine_tokens_existentes(self):
        claros, escuros = tokens_claros(), _tokens(bloco_escuro())
        self.assertFalse(set(escuros) - set(claros), "token do tema escuro sem equivalente no claro")
        # Toda cor do tema claro tem versão escura, exceto as que servem aos dois temas.
        self.assertEqual(set(claros) - set(escuros), {"cor-destaque", "cor-texto-botao", "cor-menu-ativo"})

    def test_contraste_de_texto_nos_dois_temas(self):
        for nome, tokens in (("claro", tokens_claros()), ("escuro", tokens_escuros())):
            for texto, fundo in PARES_DE_TEXTO:
                with self.subTest(tema=nome, texto=texto, fundo=fundo):
                    self.assertGreaterEqual(contraste(tokens[texto], tokens[fundo]), 4.5)

    def test_contraste_de_elementos_graficos_nos_dois_temas(self):
        for nome, tokens in (("claro", tokens_claros()), ("escuro", tokens_escuros())):
            for cor, fundo in PARES_GRAFICOS:
                with self.subTest(tema=nome, cor=cor, fundo=fundo):
                    self.assertGreaterEqual(contraste(tokens[cor], tokens[fundo]), 3.0)

    def test_tema_claro_e_o_padrao_e_impressao_continua_clara(self):
        conteudo = css()
        self.assertIn("color-scheme: light;", re.search(r":root\s*\{(.*?)\n\}", conteudo, re.S).group(1))
        self.assertIn("color-scheme: dark;", bloco_escuro())
        # O tema escuro só vale na tela; não depende da preferência do sistema operacional.
        self.assertEqual(conteudo.count('html[data-tema="escuro"] {'), 1)
        self.assertNotIn("prefers-color-scheme", conteudo)

    def test_componentes_sem_fundo_branco_fixo(self):
        conteudo = css()
        for seletor in (".campo input, .campo select, .campo textarea {", ".filtros input, .filtros select {",
                        ".botao--secundario {", ".botao--perigo {"):
            bloco = conteudo.split(seletor, 1)[1].split("}", 1)[0]
            with self.subTest(seletor=seletor):
                self.assertNotIn("#fff", bloco)

    def test_cores_dos_tipos_de_compromisso(self):
        claros = tokens_claros()
        # Prazo vermelho, tarefa azul, compromisso verde (canal dominante da cor de acento).
        for tipo, canal in (("prazo", 0), ("tarefa", 2), ("compromisso", 1)):
            cor = claros[f"tipo-{tipo}-acento"]
            canais = [int(cor[i:i + 2], 16) for i in (1, 3, 5)]
            with self.subTest(tipo=tipo):
                self.assertEqual(canais.index(max(canais)), canal)


class AlternanciaDeTemaTests(f.Cenario):
    def test_script_do_head_aplica_tema_salvo_antes_do_css(self):
        html = self.client.get(reverse("usuarios:login")).content.decode()
        cabeca = html.split("</head>", 1)[0]
        self.assertIn(f'localStorage.getItem("{CHAVE}")', cabeca)
        self.assertLess(cabeca.index("data-tema"), cabeca.index("css/app.css"))
        # Sem tema salvo, nada é aplicado: o padrão é o claro.
        self.assertIn('<html lang="pt-BR">', html)

    def test_botao_nas_paginas_sem_login(self):
        html = self.client.get(reverse("usuarios:login")).content.decode()
        self.assertEqual(html.count("data-alternar-tema"), 1)
        self.assertIn("botao-tema--flutuante", html)

    def test_botao_no_menu_e_na_barra_do_topo(self):
        self.entrar(self.ast)
        html = self.client.get(reverse("core:painel")).content.decode()
        self.assertEqual(html.count("data-alternar-tema"), 2)
        self.assertIn("botao-tema--menu", html)
        self.assertIn("botao-tema--topo", html)
        self.assertNotIn("botao-tema--flutuante", html)
        botao = re.search(r"<button[^>]*data-alternar-tema[^>]*>", html).group(0)
        self.assertIn('type="button"', botao)              # não envia formulários
        self.assertIn('aria-pressed="false"', botao)       # estado anunciado por leitores de tela
        self.assertIn("hidden", botao)                     # só aparece com JavaScript
        self.assertIn("Modo escuro", html)

    def test_javascript_persiste_e_sincroniza_o_tema(self):
        js = (ESTATICOS / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn(f'"{CHAVE}"', js)
        self.assertIn("localStorage.setItem(CHAVE_TEMA", js)
        self.assertIn('addEventListener("storage"', js)
        self.assertIn('setAttribute("aria-pressed"', js)
