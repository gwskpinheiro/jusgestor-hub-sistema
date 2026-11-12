"""Geração dos relatórios (RF08, RN09).

Cada gerador recebe o usuário e os filtros já validados e devolve um
``Resultado`` com colunas, linhas, resumo e um gráfico simples (barras em
HTML/CSS, sem bibliotecas externas). Todas as consultas partem dos conjuntos
autorizados de apps.core.acesso.
"""
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field

from django.db.models import Exists, OuterRef, Sum
from django.utils import timezone

from apps.agenda.models import Destaque
from apps.core.acesso import (
    compromissos_visiveis,
    e_adm,
    processos_visiveis,
    registros_hora_visiveis,
)
from apps.core.templatetags.formatos import duracao, moeda
from apps.financeiro.models import CobrancaHora, LancamentoFinanceiro, SituacaoLancamento, TipoLancamento

LIMITE_HTML = 1000


@dataclass
class Celula:
    texto: str
    csv: str
    classe: str = ""


@dataclass
class Resultado:
    colunas: list
    linhas: list = field(default_factory=list)
    resumo: list = field(default_factory=list)
    grafico_titulo: str = ""
    grafico: list = field(default_factory=list)

    @property
    def vazio(self):
        return not self.linhas


def c(texto, csv=None, classe=""):
    texto = "" if texto is None else str(texto)
    return Celula(texto or "—", texto if csv is None else str(csv), classe)


def data_br(valor):
    if not valor:
        return ""
    if hasattr(valor, "hour"):
        return timezone.localtime(valor).strftime("%d/%m/%Y %H:%M")
    return valor.strftime("%d/%m/%Y")


def decimal_br(valor):
    return f"{valor:.2f}".replace(".", ",")


def barras(itens, formatar=str):
    """[(rótulo, valor)] -> itens com largura proporcional ao maior valor."""
    maximo = max((v for _, v in itens), default=0) or 1
    return [{"rotulo": r, "valor": v, "texto": formatar(v), "pct": round(100 * v / maximo)} for r, v in itens]


def _periodo(qs, campo, filtros):
    if filtros.get("de"):
        qs = qs.filter(**{f"{campo}__gte": filtros["de"]})
    if filtros.get("ate"):
        qs = qs.filter(**{f"{campo}__lte": filtros["ate"]})
    return qs


def processos(usuario, f):
    qs = _periodo(processos_visiveis(usuario), "criado_em__date", f).select_related("cliente", "responsavel")
    if f.get("situacao"):
        qs = qs.filter(situacao=f["situacao"])
    arquivados = f.get("arquivados") or "nao"
    if arquivados == "nao":
        qs = qs.filter(arquivado=False)
    elif arquivados == "sim":
        qs = qs.filter(arquivado=True)
    if f.get("responsavel"):
        qs = qs.filter(responsavel=f["responsavel"])
    qs = qs.order_by("titulo")

    r = Resultado(colunas=["Número", "Título", "Cliente", "Responsável", "Situação", "Arquivado", "Cadastro"])
    for p in qs:
        r.linhas.append([
            c(p.numero), c(p.titulo), c(p.cliente.nome), c(p.responsavel.nome), c(p.get_situacao_display()),
            c("Sim" if p.arquivado else "Não"), c(data_br(p.criado_em)),
        ])
    contagem = OrderedDict()
    for p in qs:
        chave = "Arquivado" if p.arquivado else p.get_situacao_display()
        contagem[chave] = contagem.get(chave, 0) + 1
    r.resumo = [("Processos", len(r.linhas))]
    r.grafico_titulo = "Processos por situação"
    r.grafico = barras(list(contagem.items()))
    return r


def agenda(usuario, f):
    qs = _periodo(compromissos_visiveis(usuario), "inicio__date", f).select_related("responsavel", "processo")
    for campo in ("situacao", "tipo", "processo"):
        if f.get(campo):
            qs = qs.filter(**{campo: f[campo]})
    qs = qs.order_by("inicio")
    visiveis = set(processos_visiveis(usuario).values_list("pk", flat=True)) if not e_adm(usuario) else None
    agora = timezone.now()
    r = Resultado(colunas=["Data e hora", "Título", "Tipo", "Responsável", "Processo", "Situação", "Destaque"])
    contagem = defaultdict(int)
    for comp in qs:
        if comp.processo_id is None:
            processo = ""
        elif visiveis is None or comp.processo_id in visiveis:
            processo = str(comp.processo)
        else:
            # Participar do compromisso não concede acesso ao processo.
            processo = "(processo sem acesso)"
        destaque = comp.destaque(agora)
        r.linhas.append([
            c(data_br(comp.inicio)), c(comp.titulo), c(comp.get_tipo_display()), c(comp.responsavel.nome),
            c(processo), c(comp.get_situacao_display()),
            c(Destaque(destaque).label if destaque else "", classe=f"selo selo--{destaque}" if destaque else ""),
        ])
        contagem[comp.get_situacao_display()] += 1
    r.resumo = [("Compromissos", len(r.linhas))]
    r.grafico_titulo = "Compromissos por situação"
    r.grafico = barras(sorted(contagem.items()))
    return r


def horas(usuario, f):
    qs = _periodo(registros_hora_visiveis(usuario), "data_atividade", f).select_related("usuario", "processo")
    if f.get("processo"):
        qs = qs.filter(processo=f["processo"])
    if f.get("usuario_filtro"):
        qs = qs.filter(usuario=f["usuario_filtro"])
    ativa = CobrancaHora.objects.filter(registro_hora=OuterRef("pk"), liberado_em__isnull=True)
    qs = qs.annotate(cobrado=Exists(ativa)).order_by("data_atividade", "usuario__nome")
    r = Resultado(colunas=["Data", "Usuário", "Processo", "Atividade", "Duração", "Minutos", "Cobrado"])
    for h in qs:
        r.linhas.append([
            c(data_br(h.data_atividade)), c(h.usuario.nome), c(str(h.processo)), c(h.atividade),
            c(duracao(h.minutos)), c(h.minutos), c("Sim" if h.cobrado else "Não"),
        ])
    total = qs.aggregate(t=Sum("minutos"))["t"] or 0
    por_processo = (qs.values("processo__titulo").annotate(total=Sum("minutos")).order_by("-total")[:10])
    r.resumo = [("Registros", len(r.linhas)), ("Total de horas", duracao(total))]
    r.grafico_titulo = "Horas por processo (10 maiores)"
    r.grafico = barras([(p["processo__titulo"], p["total"]) for p in por_processo], duracao)
    return r


def financeiro(usuario, f):
    qs = _periodo(LancamentoFinanceiro.objects.all(), "vencimento", f).select_related("cliente", "processo")
    for campo in ("tipo", "situacao"):
        if f.get(campo):
            qs = qs.filter(**{campo: f[campo]})
    qs = qs.order_by("vencimento")
    r = Resultado(colunas=["Vencimento", "Tipo", "Descrição", "Cliente", "Processo", "Valor", "Situação", "Quitação"])
    for lanc in qs:
        r.linhas.append([
            c(data_br(lanc.vencimento)), c(lanc.get_tipo_display()), c(lanc.descricao),
            c(lanc.cliente.nome if lanc.cliente else ""), c(str(lanc.processo) if lanc.processo else ""),
            c(moeda(lanc.valor), decimal_br(lanc.valor), classe="numero"), c(lanc.get_situacao_display()),
            c(data_br(lanc.data_quitacao)),
        ])

    def soma(**filtro):
        return qs.filter(**filtro).aggregate(t=Sum("valor"))["t"] or 0

    receitas = soma(tipo=TipoLancamento.RECEITA, situacao=SituacaoLancamento.QUITADO)
    despesas = soma(tipo=TipoLancamento.DESPESA, situacao=SituacaoLancamento.QUITADO)
    r.resumo = [
        ("Lançamentos", len(r.linhas)),
        ("Receitas quitadas", moeda(receitas)), ("Despesas quitadas", moeda(despesas)),
        ("Saldo quitado", moeda(receitas - despesas)),
        ("A receber (pendente)", moeda(soma(tipo=TipoLancamento.RECEITA, situacao=SituacaoLancamento.PENDENTE))),
        ("A pagar (pendente)", moeda(soma(tipo=TipoLancamento.DESPESA, situacao=SituacaoLancamento.PENDENTE))),
    ]
    meses = defaultdict(lambda: {TipoLancamento.RECEITA: 0, TipoLancamento.DESPESA: 0})
    for item in (qs.exclude(situacao=SituacaoLancamento.CANCELADO)
                 .values("vencimento__year", "vencimento__month", "tipo").annotate(total=Sum("valor"))):
        meses[(item["vencimento__year"], item["vencimento__month"])][item["tipo"]] += item["total"]
    itens = []
    for (ano, mes), valores in sorted(meses.items()):
        itens.append((f"{mes:02d}/{ano} receitas", valores[TipoLancamento.RECEITA]))
        itens.append((f"{mes:02d}/{ano} despesas", valores[TipoLancamento.DESPESA]))
    r.grafico_titulo = "Receitas e despesas por mês de vencimento (exceto canceladas)"
    r.grafico = barras(itens, moeda)
    for item in r.grafico:
        item["classe"] = "barra--despesa" if item["rotulo"].endswith("despesas") else "barra--receita"
    return r
