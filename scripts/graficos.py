#!/usr/bin/env python3
"""Gera graficos de barras agrupadas (modelo do enunciado) a partir de consolidado/combinacoes.csv.

Por cenario: tempo medio x usuarios, P95 x usuarios, falhas x usuarios (barras = 1/2/3
instancias) e RPS x instancias, tempo medio x instancias (barras = niveis de carga).
Barras: media das repeticoes; hastes: desvio padrao. Executar no conteiner de analise:
  docker compose --profile ferramentas run --rm analise python scripts/graficos.py resultados/<maquina>/<campanha>
"""
import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

# Tres primeiros slots da paleta categorica de referencia (validada para todos os pares).
CORES = ['#2a78d6', '#eb6834', '#1baf7a']
TEXTO, TEXTO_2, GRADE = '#0b0b0b', '#52514e', '#e4e3df'
NOMES_CENARIOS = {'imagem-1mb': 'Cenario 1 - post com imagem de ~1 MB',
                  'texto-400kb': 'Cenario 2 - post com texto de ~400 kB',
                  'imagem-300kb': 'Cenario 3 - post com imagem de ~300 kB'}
NIVEIS = ['baixa', 'media', 'alta']
METRICAS = {
    'tempo_medio_ms': ('Tempo medio de resposta (ms)', 'tempo-medio'),
    'p95_ms': ('Tempo de resposta P95 (ms)', 'p95'),
    'rps': ('Requisicoes por segundo (req/s)', 'rps'),
    'falhas_pct': ('Falhas (% das requisicoes)', 'falhas'),
}

plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.edgecolor': TEXTO_2,
                     'axes.labelcolor': TEXTO, 'xtick.color': TEXTO_2, 'ytick.color': TEXTO_2,
                     'axes.spines.top': False, 'axes.spines.right': False})


def ler(pasta):
    with (pasta / 'consolidado' / 'combinacoes.csv').open(newline='', encoding='utf-8') as entrada:
        return list(csv.DictReader(entrada))


def formatar(valor):
    if valor >= 1000:
        return f'{valor / 1000:.1f}k'
    if valor >= 100:
        return f'{valor:.0f}'
    if valor >= 10:
        return f'{valor:.1f}'
    return f'{valor:.2f}'


def barras_agrupadas(ax, grupos, series, valor, desvio, rotulo_serie, largura_total=0.78):
    """grupos: valores no eixo X; series: ate 3 valores, cada um com uma cor fixa."""
    largura = largura_total / len(series)
    maximo = 0
    for indice, serie in enumerate(series):
        posicoes, alturas, erros = [], [], []
        for g, grupo in enumerate(grupos):
            v = valor(grupo, serie)
            if v is None:
                continue
            posicoes.append(g - largura_total / 2 + largura * (indice + 0.5))
            alturas.append(v)
            erros.append(desvio(grupo, serie) or 0)
            maximo = max(maximo, v + (erros[-1] or 0))
        ax.bar(posicoes, alturas, largura * 0.92, color=CORES[indice], label=rotulo_serie(serie),
               yerr=erros, error_kw={'elinewidth': 1, 'ecolor': TEXTO_2, 'capsize': 2}, zorder=3)
        for x, h, e in zip(posicoes, alturas, erros):
            ax.text(x, h + e, formatar(h), ha='center', va='bottom', fontsize=7.5, color=TEXTO, zorder=4)
    ax.set_xticks(range(len(grupos)))
    ax.yaxis.grid(True, color=GRADE, linewidth=0.8, zorder=0)
    ax.set_ylim(0, maximo * 1.15 if maximo else 1)
    ax.legend(frameon=False, fontsize=9, loc='upper left', bbox_to_anchor=(1.0, 1.0))


def figura(titulo, subtitulo):
    fig, ax = plt.subplots(figsize=(8, 4.4), dpi=150)
    fig.suptitle(titulo, x=0.02, ha='left', fontsize=12, color=TEXTO, fontweight='bold')
    ax.set_title(subtitulo, loc='left', fontsize=9, color=TEXTO_2)
    return fig, ax


def gerar(pasta):
    linhas = ler(pasta)
    destino = pasta / 'graficos'
    destino.mkdir(exist_ok=True)
    maquina = linhas[0]['maquina']
    usuarios_por_nivel = {l['nivel']: int(l['usuarios']) for l in linhas}
    niveis = [n for n in NIVEIS if n in usuarios_por_nivel]
    instancias = sorted({int(l['instancias']) for l in linhas})
    repeticoes = sorted({int(l['repeticoes']) for l in linhas})
    indice = {(l['cenario'], int(l['instancias']), l['nivel']): l for l in linhas}
    gerados = []

    def obter(cenario, inst, nivel, campo):
        linha = indice.get((cenario, inst, nivel))
        if linha is None or linha.get(campo) in ('', None):
            return None
        return float(linha[campo])

    for cenario in [c for c in NOMES_CENARIOS if any(l['cenario'] == c for l in linhas)]:
        rodape = (f'{NOMES_CENARIOS[cenario]} | {maquina} | media de {"/".join(map(str, repeticoes))} '
                  'repeticoes; hastes = desvio padrao')
        # Metricas x numero de usuarios, uma barra por quantidade de instancias.
        for metrica in ('tempo_medio_ms', 'p95_ms', 'falhas_pct', 'rps'):
            rotulo, sufixo = METRICAS[metrica]
            fig, ax = figura(f'{rotulo.split(" (")[0]} x numero de usuarios', rodape)
            barras_agrupadas(ax, niveis, instancias,
                             lambda nivel, inst: obter(cenario, inst, nivel, f'{metrica}_media'),
                             lambda nivel, inst: obter(cenario, inst, nivel, f'{metrica}_desvio'),
                             lambda inst: f'{inst} instancia' + ('s' if inst > 1 else ''))
            ax.set_xticklabels([f'{usuarios_por_nivel[n]}\n(carga {n})' for n in niveis])
            ax.set_xlabel('Numero de usuarios simultaneos (Locust)')
            ax.set_ylabel(rotulo)
            nome = destino / f'{cenario}_{sufixo}_x_usuarios.png'
            fig.savefig(nome, bbox_inches='tight')
            plt.close(fig)
            gerados.append(nome)
        # Metricas x numero de instancias, uma barra por nivel de carga.
        for metrica in ('rps', 'tempo_medio_ms'):
            rotulo, sufixo = METRICAS[metrica]
            fig, ax = figura(f'{rotulo.split(" (")[0]} x numero de instancias', rodape)
            barras_agrupadas(ax, instancias, niveis,
                             lambda inst, nivel: obter(cenario, inst, nivel, f'{metrica}_media'),
                             lambda inst, nivel: obter(cenario, inst, nivel, f'{metrica}_desvio'),
                             lambda nivel: f'{usuarios_por_nivel[nivel]} usuarios ({nivel})')
            ax.set_xticklabels([str(i) for i in instancias])
            ax.set_xlabel('Numero de instancias WordPress')
            ax.set_ylabel(rotulo)
            nome = destino / f'{cenario}_{sufixo}_x_instancias.png'
            fig.savefig(nome, bbox_inches='tight')
            plt.close(fig)
            gerados.append(nome)

    # Painel comparativo: tempo medio de todos os cenarios lado a lado.
    cenarios = [c for c in NOMES_CENARIOS if any(l['cenario'] == c for l in linhas)]
    fig, eixos = plt.subplots(1, len(cenarios), figsize=(5 * len(cenarios), 4.2), dpi=150, squeeze=False)
    for ax, cenario in zip(eixos[0], cenarios):
        barras_agrupadas(ax, niveis, instancias,
                         lambda nivel, inst: obter(cenario, inst, nivel, 'tempo_medio_ms_media'),
                         lambda nivel, inst: obter(cenario, inst, nivel, 'tempo_medio_ms_desvio'),
                         lambda inst: f'{inst} inst.')
        ax.set_xticklabels([str(usuarios_por_nivel[n]) for n in niveis])
        ax.set_title(NOMES_CENARIOS[cenario], loc='left', fontsize=9, color=TEXTO)
        ax.set_xlabel('Numero de usuarios')
        ax.set_ylabel('Tempo medio de resposta (ms)')
    fig.suptitle(f'Tempo medio de resposta por cenario - {maquina}', x=0.01, ha='left',
                 fontsize=12, fontweight='bold', color=TEXTO)
    fig.tight_layout()
    nome = destino / 'painel_tempo_medio.png'
    fig.savefig(nome, bbox_inches='tight')
    plt.close(fig)
    gerados.append(nome)
    print(f'{len(gerados)} graficos em {destino}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('campanha', type=Path)
    gerar(parser.parse_args().campanha)
