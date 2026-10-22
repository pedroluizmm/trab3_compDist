# Preparacao do Trabalho 3 no Windows — APPLY 1

Esta copia usa o worktree C:\compDist\Trabalho3-Docker e a branch
trabalho3/windows-preparacao. O Trabalho 2 original permanece em
C:\compDist\Trabalho-Docker. Worktrees compartilham o repositorio Git;
os arquivos de trabalho e dados locais ficam separados.

## Compatibilidade

Execute o preparador com `python scripts/preparar.py` no Windows.
Ele usa UID/GID 33:33 (www-data da imagem Debian/Apache), sem consultar
os.getuid/os.getgid. Em macOS/Linux, continua usando UID/GID do usuario local.
Os IDs sao identidades Linux dos processos, nao IDs da conta Windows.
Uma configuracao .env existente e preservada; nunca copie cegamente os IDs
501:20 do ambiente macOS anterior.

O projeto Compose chama-se trabalho3-experimento e publica apenas
127.0.0.1:8086. As cinco imagens/servicos, redes e montagens foram preservados.
O nome isola recursos Compose, mas a porta do host continua compartilhada:
nao execute simultaneamente outro projeto que publique 8086.

O script shell usa LF, protegido por .gitattributes. Ele e invocado por /bin/sh
dentro do conteiner Linux; nao requer shell instalado no Windows.

## Arquivos locais

O preparador cria .env, segredos/, html/ e data/mysql/, preservando existentes.
Os tres segredos sao gerados localmente e nao sao exibidos. Os arquivos sao
UTF-8 com LF. .gitignore exclui credenciais e dados persistentes.
html/wp-config.php e apenas um placeholder vazio para o bind mount.
Nao ha instalacao WordPress nem dados restaurados nesta etapa.

No Windows, as ACLs NTFS controlam o acesso; modo POSIX 0600 nao garante
isolamento equivalente. Os secrets herdarao permissoes do diretorio local.
Nao publique nem compartilhe a pasta segredos/. Nao altere segredos isoladamente
apos inicializar o banco; preserve dados e credenciais correspondentes.

A inspecao local encontrou ACLs herdadas que permitem leitura a Usuarios e
modificacao a Usuarios autenticados. A tentativa de restringir somente esta
pasta via Set-Acl foi negada pelo Windows (UnauthorizedAccessException).
Assim, o isolamento das credenciais entre contas locais permanece pendente;
exclusao do Git nao equivale a protecao por ACL. Nenhuma permissao global foi
alterada. Uma conta com direito de alterar a ACL devera tratar esta pendencia.

## Validacao e limites

`docker compose config --quiet` valida a resolucao sem iniciar conteineres.
As montagens no disco Windows e a escrita com UID/GID 33:33 ainda precisam
ser verificadas na primeira inicializacao autorizada. Compartilhamento do
Docker Desktop e ACLs podem afetar acesso, e armazenamento NTFS pode afetar
medicoes de desempenho. Nenhuma permissao global foi alterada.

O script verificar.py continua sendo o verificador do Trabalho 2: exige cinco
servicos e tres upstreams e grava evidencias. Nao foi executado nesta etapa.
Os arquivos de evidencias herdados continuam sendo exclusivamente historicos.

Antes de comparar carga, faltam instalar WordPress, definir dados reproduziveis,
adaptar cenarios de 1/2/3 instancias e adicionar Locust em uma etapa autorizada.
Nao ha Locust nesta revisao. Para o APPLY 1 nao iniciar conteineres, baixar
imagens, instalar WordPress ou executar testes de carga.

## Resultado das verificacoes do APPLY 1

- Todos os scripts Python compilaram em memoria, sem gerar bytecode.
- Identidade Windows 33:33 validada; ramo POSIX validado por simulacao dos IDs.
- Reexecucao do preparador preservou .env, os tres segredos e o placeholder.
- Shell validado com bash -n do Git for Windows; arquivo confirmado em LF.
- docker compose config --quiet e inspecao do JSON resolvido aprovados.
- Cinco servicos, imagens, redes, UID/GID e caminhos de montagem conferidos.
- .env, segredos e dados confirmados como ignorados pelo Git.
- Porta 8086 sem listener no momento da consulta.
- Nenhum conteiner iniciado; nenhuma imagem baixada; nenhum teste de carga.

Esses resultados comprovam preparacao estatica. Nao comprovam escrita dos
conteineres nos bind mounts nem uma instalacao funcional do WordPress.
