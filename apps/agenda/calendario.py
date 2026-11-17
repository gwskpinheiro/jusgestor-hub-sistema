"""Visualização de calendário da agenda (RF04): dia, semana, mês e ano.

Montado no servidor, sem bibliotecas: calcula o período, busca os compromissos
VISÍVEIS ao usuário (o queryset recebido já vem de compromissos_visiveis, RN07)
e organiza-os em grades. Não calcula prazos: usa apenas as datas informadas.

A posição de cada compromisso é a data e a hora de início, no fuso do sistema.
"""
import calendar as _calendario
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

VISOES = ("dia", "semana", "mes", "ano")
VISAO_PADRAO = "mes"
MAX_EVENTOS_NO_DIA_DO_MES = 3
ANO_MINIMO, ANO_MAXIMO = 1901, 2099
HORA_INICIAL_PADRAO, HORA_FINAL_PADRAO = 7, 19
DIAS_DA_SEMANA = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro")


def ler_visao(valor):
    return valor if valor in VISOES else VISAO_PADRAO


def ler_data(valor, hoje):
    """Data AAAA-MM-DD do parâmetro; inválida ou fora de 1901–2099: hoje."""
    try:
        lida = date.fromisoformat(valor or "")
    except ValueError:
        return hoje
    return lida if ANO_MINIMO <= lida.year <= ANO_MAXIMO else hoje


def _limitar(d, fallback):
    return d if ANO_MINIMO <= d.year <= ANO_MAXIMO else fallback


def _primeiro_do_mes(ano, mes):
    return date(ano, mes, 1)


def _somar_meses(d, meses):
    indice = d.year * 12 + (d.month - 1) + meses
    return date(indice // 12, indice % 12 + 1, 1)


@dataclass
class Periodo:
    visao: str
    referencia: date
    inicio: date          # primeiro dia exibido
    fim: date             # dia seguinte ao último exibido (exclusivo)
    anterior: date
    proximo: date
    titulo: str


def periodo(visao, ref):
    if visao == "dia":
        titulo = f"{_nome_dia_semana(ref)}, {ref.day} de {MESES[ref.month - 1]} de {ref.year}"
        return Periodo(visao, ref, ref, ref + timedelta(days=1),
                       _limitar(ref - timedelta(days=1), ref), _limitar(ref + timedelta(days=1), ref), titulo)
    if visao == "semana":
        inicio = ref - timedelta(days=ref.weekday())          # semanas começam na segunda-feira
        fim = inicio + timedelta(days=7)
        ultimo = fim - timedelta(days=1)
        titulo = (f"{inicio.day} de {MESES[inicio.month - 1]} a {ultimo.day} de {MESES[ultimo.month - 1]} de {ultimo.year}"
                  if inicio.year == ultimo.year else
                  f"{inicio:%d/%m/%Y} a {ultimo:%d/%m/%Y}")
        return Periodo(visao, ref, inicio, fim, _limitar(ref - timedelta(days=7), ref),
                       _limitar(ref + timedelta(days=7), ref), f"Semana de {titulo}")
    if visao == "ano":
        inicio = date(ref.year, 1, 1)
        return Periodo(visao, ref, inicio, date(ref.year + 1, 1, 1),
                       date(ref.year - 1, 1, 1) if ref.year > ANO_MINIMO else inicio,
                       date(ref.year + 1, 1, 1) if ref.year < ANO_MAXIMO else inicio, str(ref.year))
    # mês
    inicio = _primeiro_do_mes(ref.year, ref.month)
    return Periodo("mes", ref, inicio, _somar_meses(inicio, 1),
                   _limitar(_somar_meses(inicio, -1), inicio), _limitar(_somar_meses(inicio, 1), inicio),
                   f"{MESES[ref.month - 1].capitalize()} de {ref.year}")


def _nome_dia_semana(d):
    return ("Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
            "Sexta-feira", "Sábado", "Domingo")[d.weekday()]


def _limites(inicio, fim):
    fuso = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(inicio, time.min), fuso),
            timezone.make_aware(datetime.combine(fim, time.min), fuso))


def compromissos_no_intervalo(qs, inicio, fim, agora):
    """Compromissos com início entre as datas (fim exclusivo), com destaque calculado (RN02)."""
    de, ate = _limites(inicio, fim)
    itens = list(qs.filter(inicio__gte=de, inicio__lt=ate).select_related("responsavel").order_by("inicio", "pk"))
    for item in itens:
        item.destaque_atual = item.destaque(agora)
        item.inicio_local = timezone.localtime(item.inicio)
    return itens


def por_dia(itens):
    dias = {}
    for item in itens:
        dias.setdefault(item.inicio_local.date(), []).append(item)
    return dias


@dataclass
class Dia:
    data: date
    hoje: bool
    no_mes: bool = True
    eventos: list = field(default_factory=list)
    excedentes: int = 0


def intervalo_grade_mes(ref):
    """Primeiro dia exibido (segunda-feira) e dia seguinte ao último da grade do mês."""
    inicio_mes = _primeiro_do_mes(ref.year, ref.month)
    _, dias_no_mes = _calendario.monthrange(ref.year, ref.month)
    inicio = inicio_mes - timedelta(days=inicio_mes.weekday())
    semanas = -(-(inicio_mes.weekday() + dias_no_mes) // 7)
    return inicio, inicio + timedelta(days=semanas * 7)


def grade_mes(ref, itens_por_dia, hoje):
    """Semanas (segunda a domingo) que cobrem o mês; dias de fora aparecem esmaecidos."""
    inicio, fim = intervalo_grade_mes(ref)
    semanas = (fim - inicio).days // 7
    grade = []
    for s in range(semanas):
        semana = []
        for d in range(7):
            dia = inicio + timedelta(days=s * 7 + d)
            eventos = itens_por_dia.get(dia, [])
            semana.append(Dia(dia, dia == hoje, dia.month == ref.month,
                              eventos[:MAX_EVENTOS_NO_DIA_DO_MES], max(0, len(eventos) - MAX_EVENTOS_NO_DIA_DO_MES)))
        grade.append(semana)
    return grade


def grade_horas(dias, itens_por_dia):
    """Linhas por hora (dia e semana). Mostra das 7h às 19h, ampliando se houver eventos fora."""
    horas = [item.inicio_local.hour for d in dias for item in itens_por_dia.get(d, [])]
    primeira = min([HORA_INICIAL_PADRAO] + horas)
    ultima = max([HORA_FINAL_PADRAO] + horas)
    linhas = []
    for hora in range(primeira, ultima + 1):
        celulas = [[item for item in itens_por_dia.get(d, []) if item.inicio_local.hour == hora] for d in dias]
        linhas.append({"hora": hora, "celulas": celulas})
    return linhas


def resumo_ano(qs, ano, hoje):
    """Contagem por dia e por tipo no ano (uma consulta agregada) e mini calendários dos 12 meses."""
    de, ate = _limites(date(ano, 1, 1), date(ano + 1, 1, 1))
    linhas = (qs.filter(inicio__gte=de, inicio__lt=ate)
              .annotate(dia=TruncDate("inicio", tzinfo=timezone.get_current_timezone()))
              .values("dia", "tipo").annotate(n=Count("id")).order_by())
    por_dia = {}
    for linha in linhas:
        por_dia.setdefault(linha["dia"], {})[linha["tipo"]] = linha["n"]
    meses = []
    for mes in range(1, 13):
        inicio_mes = date(ano, mes, 1)
        _, dias_no_mes = _calendario.monthrange(ano, mes)
        totais = {"compromisso": 0, "tarefa": 0, "prazo": 0}
        semanas, semana = [], [None] * inicio_mes.weekday()
        for dia_num in range(1, dias_no_mes + 1):
            dia = date(ano, mes, dia_num)
            tipos = por_dia.get(dia, {})
            for tipo, n in tipos.items():
                totais[tipo] = totais.get(tipo, 0) + n
            semana.append({"data": dia, "hoje": dia == hoje, "tipos": sorted(tipos), "total": sum(tipos.values())})
            if len(semana) == 7:
                semanas.append(semana)
                semana = []
        if semana:
            semanas.append(semana + [None] * (7 - len(semana)))
        meses.append({"data": inicio_mes, "nome": MESES[mes - 1].capitalize(), "semanas": semanas,
                      "totais": totais, "total": sum(totais.values())})
    return meses
