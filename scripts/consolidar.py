#!/usr/bin/env python3
"""Consolida resumo_execucoes.csv de uma campanha em CSVs por combinacao.

Saida em resultados/<maquina>/<campanha>/consolidado/:
  combinacoes.csv          27 linhas: instancias x nivel x cenario (media e desvio das repeticoes)
  inst<N>_carga-<nivel>.csv  9 arquivos: cada um agrupa os 3 cenarios de uma
                           combinacao (instancias, nivel de carga)
  execucoes_brutas.csv     uma linha por execucao (todas as repeticoes)
Somente biblioteca padrao: roda no host ou no conteiner de analise.
"""
import argparse
import csv
import shutil
import statistics
from pathlib import Path

ORDEM_CENARIOS = ['imagem-1mb', 'texto-400kb', 'imagem-300kb']
ORDEM_NIVEIS = ['baixa', 'media', 'alta']
METRICAS = ['tempo_medio_ms', 'p95_ms', 'rps', 'falhas_pct', 'mediana_ms', 'p99_ms',
            'pagina_tempo_medio_ms', 'pagina_p95_ms', 'pagina_rps',
            'imagem_tempo_medio_ms', 'imagem_p95_ms', 'imagem_rps']
CAMPOS = (['maquina', 'campanha', 'instancias', 'nivel', 'usuarios', 'cenario', 'repeticoes',
           'requisicoes_total', 'falhas_total']
          + [f'{m}_{s}' for m in METRICAS for s in ('media', 'desvio')]
          + ['locust_cpu_max_pct', 'execucoes_com_alerta_cpu', 'execucoes_com_incidentes'])


def numero(valor):
    return float(valor) if valor not in ('', None) else None


def agregar(linhas):
    base = linhas[0]
    saida = {'maquina': base['maquina'], 'campanha': base['campanha'], 'instancias': int(base['instancias']),
             'nivel': base['nivel'], 'usuarios': int(base['usuarios']), 'cenario': base['cenario'],
             'repeticoes': len(linhas),
             'requisicoes_total': sum(int(l['requisicoes']) for l in linhas),
             'falhas_total': sum(int(l['falhas']) for l in linhas)}
    for metrica in METRICAS:
        valores = [v for v in (numero(l[metrica]) for l in linhas) if v is not None]
        saida[f'{metrica}_media'] = round(statistics.mean(valores), 3) if valores else ''
        saida[f'{metrica}_desvio'] = round(statistics.stdev(valores), 3) if len(valores) > 1 else (0 if valores else '')
    cpu = [v for v in (numero(l['locust_cpu_max_pct']) for l in linhas) if v is not None]
    saida['locust_cpu_max_pct'] = max(cpu) if cpu else ''
    saida['execucoes_com_alerta_cpu'] = sum(l['locust_alerta_cpu'] == 'True' for l in linhas)
    saida['execucoes_com_incidentes'] = sum(bool(l['incidentes']) for l in linhas)
    return saida


def escrever(caminho, linhas):
    with caminho.open('w', newline='', encoding='utf-8') as saida:
        escritor = csv.DictWriter(saida, fieldnames=CAMPOS)
        escritor.writeheader()
        escritor.writerows(linhas)


def ordem(linha):
    return (linha['instancias'], ORDEM_NIVEIS.index(linha['nivel']) if linha['nivel'] in ORDEM_NIVEIS else 9,
            linha['usuarios'], ORDEM_CENARIOS.index(linha['cenario']))


def consolidar(pasta):
    with (pasta / 'resumo_execucoes.csv').open(newline='', encoding='utf-8') as entrada:
        execucoes = [l for l in csv.DictReader(entrada) if l['status'] in ('ok', 'com_falhas')]
    grupos = {}
    for linha in execucoes:
        grupos.setdefault((linha['instancias'], linha['nivel'], linha['cenario']), []).append(linha)
    combinacoes = sorted((agregar(g) for g in grupos.values()), key=ordem)
    destino = pasta / 'consolidado'
    destino.mkdir(exist_ok=True)
    escrever(destino / 'combinacoes.csv', combinacoes)
    arquivos = 0
    for inst in sorted({c['instancias'] for c in combinacoes}):
        for nivel in sorted({c['nivel'] for c in combinacoes}, key=lambda n: ORDEM_NIVEIS.index(n)
                            if n in ORDEM_NIVEIS else 9):
            grupo = [c for c in combinacoes if c['instancias'] == inst and c['nivel'] == nivel]
            if grupo:
                escrever(destino / f'inst{inst}_carga-{nivel}.csv', grupo)
                arquivos += 1
    shutil.copyfile(pasta / 'resumo_execucoes.csv', destino / 'execucoes_brutas.csv')
    print(f'{len(execucoes)} execucoes -> {len(combinacoes)} combinacoes, {arquivos} CSVs por '
          f'(instancias, nivel) em {destino}')
    return combinacoes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('campanha', type=Path, help='ex.: resultados/maquina-a/campanha-final')
    consolidar(parser.parse_args().campanha)
