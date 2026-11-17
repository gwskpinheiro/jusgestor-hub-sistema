"""RF04 — visualização de calendário da agenda (dia, semana, mês, ano e lista)."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.agenda import calendario as cal
from apps.core.tests import fabrica as f


def local(ano, mes, dia, hora=9, minuto=0):
    return timezone.make_aware(datetime(ano, mes, dia, hora, minuto))


class PeriodoTests(SimpleTestCase):
    def test_parametros_invalidos_usam_padroes(self):
        hoje = date(2026, 11, 16)
        self.assertEqual(cal.ler_visao("xyz"), "mes")
        self.assertEqual(cal.ler_visao(None), "mes")
        self.assertEqual(cal.ler_visao("semana"), "semana")
        self.assertEqual(cal.ler_data("2026-02-30", hoje), hoje)
        self.assertEqual(cal.ler_data("abc", hoje), hoje)
        self.assertEqual(cal.ler_data(None, hoje), hoje)
        self.assertEqual(cal.ler_data("0001-01-01", hoje), hoje)
        self.assertEqual(cal.ler_data("2027-03-05", hoje), date(2027, 3, 5))

    def test_dia(self):
        p = cal.periodo("dia", date(2026, 11, 16))
        self.assertEqual((p.inicio, p.fim), (date(2026, 11, 16), date(2026, 11, 17)))
        self.assertEqual((p.anterior, p.proximo), (date(2026, 11, 15), date(2026, 11, 17)))
        self.assertEqual(p.titulo, "Segunda-feira, 16 de novembro de 2026")

    def test_semana_comeca_na_segunda(self):
        p = cal.periodo("semana", date(2026, 11, 19))  # quinta-feira
        self.assertEqual((p.inicio, p.fim), (date(2026, 11, 16), date(2026, 11, 23)))
        self.assertEqual((p.anterior, p.proximo), (date(2026, 11, 12), date(2026, 11, 26)))
        self.assertEqual(p.titulo, "Semana de 16 de novembro a 22 de novembro de 2026")
        virada = cal.periodo("semana", date(2026, 12, 31))
        self.assertEqual(virada.titulo, "Semana de 28/12/2026 a 03/01/2027")

    def test_mes_e_virada_de_ano(self):
        p = cal.periodo("mes", date(2026, 1, 20))
        self.assertEqual((p.inicio, p.fim), (date(2026, 1, 1), date(2026, 2, 1)))
        self.assertEqual((p.anterior, p.proximo), (date(2025, 12, 1), date(2026, 2, 1)))
        self.assertEqual(p.titulo, "Janeiro de 2026")

    def test_ano(self):
        p = cal.periodo("ano", date(2026, 7, 4))
        self.assertEqual((p.inicio, p.fim), (date(2026, 1, 1), date(2027, 1, 1)))
        self.assertEqual((p.anterior, p.proximo, p.titulo), (date(2025, 1, 1), date(2027, 1, 1), "2026"))

    def test_limites_da_navegacao(self):
        self.assertEqual(cal.periodo("dia", date(2099, 12, 31)).proximo, date(2099, 12, 31))
        self.assertEqual(cal.periodo("dia", date(1901, 1, 1)).anterior, date(1901, 1, 1))
        self.assertEqual(cal.periodo("ano", date(2099, 5, 1)).proximo, date(2099, 1, 1))
        self.assertEqual(cal.periodo("mes", date(1901, 1, 9)).anterior, date(1901, 1, 1))

    def test_grade_do_mes_cobre_semanas_completas(self):
        for ref in (date(2026, 2, 10), date(2026, 3, 1), date(2026, 11, 16), date(2027, 2, 1)):
            inicio, fim = cal.intervalo_grade_mes(ref)
            with self.subTest(ref=ref):
                self.assertEqual(inicio.weekday(), 0)
                self.assertEqual((fim - inicio).days % 7, 0)
                self.assertLessEqual(inicio, ref.replace(day=1))
                self.assertGreater(fim, cal.periodo("mes", ref).fim - timedelta(days=1))
                self.assertLess((fim - inicio).days, 7 * 7)

    def test_grade_do_mes_limita_eventos_por_dia(self):
        dia = date(2026, 11, 18)
        itens = {dia: [SimpleNamespace(n=i) for i in range(5)]}
        grade = cal.grade_mes(date(2026, 11, 1), itens, hoje=date(2026, 11, 16))
        celula = next(d for semana in grade for d in semana if d.data == dia)
        self.assertEqual(len(celula.eventos), cal.MAX_EVENTOS_NO_DIA_DO_MES)
        self.assertEqual(celula.excedentes, 5 - cal.MAX_EVENTOS_NO_DIA_DO_MES)
        hoje = next(d for semana in grade for d in semana if d.hoje)
        self.assertEqual(hoje.data, date(2026, 11, 16))
        fora = [d for semana in grade for d in semana if not d.no_mes]
        self.assertTrue(all(d.data.month != 11 for d in fora))

    def test_grade_de_horas_amplia_para_eventos_fora_do_horario(self):
        dia = date(2026, 11, 16)
        cedo = SimpleNamespace(inicio_local=datetime(2026, 11, 16, 5, 30))
        tarde = SimpleNamespace(inicio_local=datetime(2026, 11, 16, 22, 0))
        linhas = cal.grade_horas([dia], {dia: [cedo, tarde]})
        self.assertEqual((linhas[0]["hora"], linhas[-1]["hora"]), (5, 22))
        self.assertEqual(linhas[0]["celulas"], [[cedo]])
        padrao = cal.grade_horas([dia], {})
        self.assertEqual((padrao[0]["hora"], padrao[-1]["hora"]),
                         (cal.HORA_INICIAL_PADRAO, cal.HORA_FINAL_PADRAO))


class CalendarioTests(f.Cenario):
    url = reverse("agenda:calendario")

    def abrir(self, usuario, **parametros):
        self.entrar(usuario)
        return self.client.get(self.url, parametros)

    def titulos(self, resposta, chave="semanas"):
        if chave == "semanas":
            return {c.titulo for semana in resposta.context["semanas"] for d in semana for c in d.eventos}
        return {c.titulo for d in resposta.context["dias"] for c in d["eventos"]}

    def test_exige_login(self):
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 302)
        self.assertIn(reverse("usuarios:login"), resposta["Location"])

    def test_mes_e_a_visao_padrao(self):
        resposta = self.abrir(self.adv)
        self.assertEqual(resposta.status_code, 200)
        self.assertTemplateUsed(resposta, "agenda/calendario.html")
        self.assertEqual(resposta.context["visao"], "mes")
        self.assertEqual(resposta.context["periodo"].referencia, timezone.localdate())

    def test_parametros_invalidos_nao_quebram(self):
        resposta = self.abrir(self.adv, visao="<script>", data="2026-13-45")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["visao"], "mes")
        self.assertNotContains(resposta, "visao=&lt;script")
        self.assertNotContains(resposta, "visao=<script")

    def test_mes_mostra_somente_eventos_autorizados_do_periodo(self):
        f.compromisso(self.adv, self.proc, titulo="Audiência própria fictícia", inicio=local(2026, 3, 10, 14))
        f.compromisso(self.adv2, self.proc2, titulo="Audiência alheia fictícia", inicio=local(2026, 3, 11, 9))
        f.compromisso(self.adv, self.proc, titulo="Prazo de abril fictício", tipo="prazo", inicio=local(2026, 4, 20))
        resposta = self.abrir(self.adv, visao="mes", data="2026-03-15")
        titulos = self.titulos(resposta)
        self.assertIn("Audiência própria fictícia", titulos)
        self.assertNotIn("Audiência alheia fictícia", titulos)   # RN07
        self.assertNotIn("Prazo de abril fictício", titulos)
        self.assertNotContains(resposta, "Audiência alheia fictícia")
        self.assertEqual(resposta.context["total"], 1)
        # O administrador vê os dois.
        self.assertEqual(self.titulos(self.abrir(self.adm, visao="mes", data="2026-03-15")),
                         {"Audiência própria fictícia", "Audiência alheia fictícia"})

    def test_participante_ve_o_evento_no_calendario(self):
        f.compromisso(self.adv2, self.proc2, participantes=[self.ast], titulo="Reunião com participante fictícia",
                      inicio=local(2026, 3, 12, 10))
        f.compromisso(self.adv2, self.proc2, titulo="Reunião sem participante fictícia", inicio=local(2026, 3, 12, 11))
        titulos = self.titulos(self.abrir(self.ast, visao="mes", data="2026-03-01"))
        self.assertEqual(titulos, {"Reunião com participante fictícia"})

    def test_evento_leva_ao_detalhe_e_indica_o_tipo(self):
        comp = f.compromisso(self.adv, self.proc, titulo="Prazo fictício de contestação", tipo="prazo",
                             inicio=local(2026, 3, 10, 14))
        resposta = self.abrir(self.adv, visao="mes", data="2026-03-10")
        self.assertContains(resposta, f'href="{comp.get_absolute_url()}"')
        self.assertContains(resposta, "evento evento--prazo")
        self.assertContains(resposta, '<span class="evento__tipo sr-only">Prazo</span>', html=False)
        self.assertEqual(self.client.get(comp.get_absolute_url()).status_code, 200)

    def test_dia_com_muitos_eventos_mostra_link_para_os_demais(self):
        for hora in range(8, 13):
            f.compromisso(self.adv, self.proc, inicio=local(2026, 3, 10, hora))
        resposta = self.abrir(self.adv, visao="mes", data="2026-03-10")
        self.assertContains(resposta, "+2 mais")
        self.assertContains(resposta, "?visao=dia&amp;data=2026-03-10")
        dia = self.client.get(self.url, {"visao": "dia", "data": "2026-03-10"})
        self.assertEqual(dia.context["total"], 5)

    def test_semana_respeita_os_limites_no_fuso_local(self):
        f.compromisso(self.adv, self.proc, titulo="Domingo à noite fictício", inicio=local(2026, 11, 22, 23, 30))
        f.compromisso(self.adv, self.proc, titulo="Segunda cedo fictícia", inicio=local(2026, 11, 16, 0, 0))
        f.compromisso(self.adv, self.proc, titulo="Próxima segunda fictícia", inicio=local(2026, 11, 23, 0, 0))
        f.compromisso(self.adv, self.proc, titulo="Domingo anterior fictício", inicio=local(2026, 11, 15, 23, 59))
        resposta = self.abrir(self.adv, visao="semana", data="2026-11-19")
        self.assertEqual(self.titulos(resposta, "dias"), {"Domingo à noite fictício", "Segunda cedo fictícia"})
        self.assertEqual([d["data"] for d in resposta.context["dias"]][0], date(2026, 11, 16))
        self.assertEqual(len(resposta.context["dias"]), 7)
        # A grade de horas se amplia para os eventos das 0h e das 23h.
        horas = [linha["hora"] for linha in resposta.context["linhas"]]
        self.assertEqual((horas[0], horas[-1]), (0, 23))

    def test_dia_e_navegacao(self):
        f.compromisso(self.adv, self.proc, titulo="Tarefa do dia fictícia", tipo="tarefa", inicio=local(2026, 3, 10, 15))
        resposta = self.abrir(self.adv, visao="dia", data="2026-03-10")
        self.assertContains(resposta, "Tarefa do dia fictícia")
        self.assertContains(resposta, "Terça-feira, 10 de março de 2026")
        self.assertContains(resposta, '?visao=dia&amp;data=2026-03-09" rel="prev"')
        self.assertContains(resposta, '?visao=dia&amp;data=2026-03-11" rel="next"')
        self.assertContains(resposta, f'?visao=dia&amp;data={timezone.localdate().isoformat()}">Hoje</a>')
        vazio = self.client.get(self.url, {"visao": "dia", "data": "2026-03-11"})
        self.assertContains(vazio, "Nenhum compromisso, tarefa ou prazo neste dia.")

    def test_abas_mantem_a_data_e_indicam_a_visao_atual(self):
        resposta = self.abrir(self.adv, visao="semana", data="2026-03-10")
        for visao in ("dia", "semana", "mes", "ano"):
            self.assertContains(resposta, f"?visao={visao}&amp;data=2026-03-10")
        self.assertContains(resposta, f'abas__item abas__item--ativa" href="{self.url}?visao=semana&amp;data=2026-03-10" aria-current="page"')
        self.assertContains(resposta, f'href="{reverse("agenda:lista")}"')

    def test_ano_conta_eventos_por_mes_e_tipo_em_uma_consulta(self):
        f.compromisso(self.adv, self.proc, tipo="prazo", inicio=local(2026, 3, 10))
        f.compromisso(self.adv, self.proc, tipo="tarefa", inicio=local(2026, 3, 10, 15))
        f.compromisso(self.adv, self.proc, tipo="compromisso", inicio=local(2026, 7, 1))
        f.compromisso(self.adv2, self.proc2, tipo="prazo", inicio=local(2026, 3, 11))       # sem acesso
        f.compromisso(self.adv, self.proc, tipo="prazo", inicio=local(2027, 1, 1, 0, 30))  # outro ano
        resposta = self.abrir(self.adv, visao="ano", data="2026-05-05")
        meses = resposta.context["meses"]
        self.assertEqual(len(meses), 12)
        self.assertEqual(meses[2]["totais"], {"compromisso": 0, "tarefa": 1, "prazo": 1})
        self.assertEqual(meses[6]["total"], 1)
        self.assertEqual(resposta.context["total"], 3)
        dia = next(d for semana in meses[2]["semanas"] for d in semana if d and d["data"] == date(2026, 3, 10))
        self.assertEqual((dia["total"], dia["tipos"]), (2, ["prazo", "tarefa"]))
        self.assertContains(resposta, "?visao=mes&amp;data=2026-03-01")

        # O número de consultas não cresce com a quantidade de eventos.
        with CaptureQueriesContext(connection) as poucos:
            self.client.get(self.url, {"visao": "ano", "data": "2026-05-05"})
        for n in range(20):
            f.compromisso(self.adv, self.proc, inicio=local(2026, 1 + n % 12, 1 + n))
        with CaptureQueriesContext(connection) as muitos:
            self.client.get(self.url, {"visao": "ano", "data": "2026-05-05"})
        self.assertEqual(len(poucos), len(muitos))

    def test_mes_com_poucos_ou_muitos_eventos_usa_as_mesmas_consultas(self):
        self.abrir(self.adv, visao="mes", data="2026-03-10")
        with CaptureQueriesContext(connection) as poucos:
            self.client.get(self.url, {"visao": "mes", "data": "2026-03-10"})
        for n in range(15):
            f.compromisso(self.adv, self.proc, inicio=local(2026, 3, 1 + n))
        with CaptureQueriesContext(connection) as muitos:
            self.client.get(self.url, {"visao": "mes", "data": "2026-03-10"})
        self.assertEqual(len(poucos), len(muitos))

    def test_endereco_antigo_com_filtros_vai_para_a_lista(self):
        self.entrar(self.adv)
        resposta = self.client.get(self.url, {"situacao": "todas", "tipo": "prazo"})
        self.assertRedirects(resposta, f"{reverse('agenda:lista')}?situacao=todas&tipo=prazo")

    def test_lista_continua_disponivel_com_filtros_e_acoes(self):
        f.compromisso(self.adv, self.proc, titulo="Tarefa listada fictícia", tipo="tarefa")
        self.entrar(self.adv)
        resposta = self.client.get(reverse("agenda:lista"), {"tipo": "tarefa"})
        self.assertContains(resposta, "Tarefa listada fictícia")
        self.assertContains(resposta, 'class="tipo tipo--tarefa"')
        self.assertContains(resposta, 'name="situacao"')
        self.assertContains(resposta, "data-confirmar=")
        self.assertContains(resposta, f'abas__item abas__item--ativa" href="{reverse("agenda:lista")}" aria-current="page"')

    def test_detalhe_volta_ao_mes_do_evento(self):
        comp = f.compromisso(self.adv, self.proc, inicio=local(2026, 3, 10, 14))
        self.entrar(self.adv)
        resposta = self.client.get(comp.get_absolute_url())
        self.assertContains(resposta, f'{self.url}?visao=mes&amp;data=2026-03-10')
        self.assertContains(resposta, 'class="tipo tipo--compromisso"')

    def test_menu_leva_ao_calendario(self):
        self.entrar(self.ast)
        resposta = self.client.get(reverse("core:painel"))
        self.assertContains(resposta, f'href="{self.url}"')

