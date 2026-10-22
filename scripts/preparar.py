#!/usr/bin/env python3
"""Prepara apenas a pasta do experimento; nao instala ou inicia software."""
import os
from pathlib import Path
import secrets

def identidade_linux():
    """Windows usa www-data da imagem Debian/Apache; POSIX usa IDs locais."""
    if os.name == 'nt':
        return 33, 33
    return os.getuid(), os.getgid()


def preparar(raiz):
    # Resolve a identidade antes de qualquer escrita.
    uid, gid = identidade_linux()
    for pasta in ['html', 'data/mysql', 'segredos']:
        (raiz / pasta).mkdir(parents=True, exist_ok=True)
    for nome in ['senha_root', 'senha_aplicacao', 'semente_sessao']:
        destino = raiz / 'segredos' / nome
        if not destino.exists():
            # Em POSIX restringe desde a abertura; no Windows valem ACLs.
            descriptor = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as arquivo:
                arquivo.write(secrets.token_hex(32) + '\n')
    config = raiz / '.env'
    if not config.exists():
        with config.open('x', encoding='utf-8', newline='\n') as arquivo:
            arquivo.write('COMPOSE_PROJECT_NAME=trabalho3-experimento\n'
                          'HTTP_PORT=8086\n'
                          'LOCAL_UID=' + str(uid) + '\n'
                          'LOCAL_GID=' + str(gid) + '\n'
                          'SITE_URL=http://127.0.0.1:8086\n')
    # Permite montar a configuracao sobre uma pasta inicialmente vazia.
    placeholder = raiz / 'html/wp-config.php'
    if not placeholder.exists():
        placeholder.touch()
    print('Pastas e segredos locais preparados; nenhum segredo foi exibido.')


if __name__ == '__main__':
    preparar(Path(__file__).resolve().parent.parent)
