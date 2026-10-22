# Decisões técnicas

A configuração foi elaborada para os requisitos da atividade: três servidores WordPress, um banco comum, Nginx como único ponto publicado e arquivos compartilhados com o host. Os documentos descrevem somente o experimento e suas dependências técnicas.

## Configuração

- O Compose define cinco serviços explicitamente, com bind mounts na sintaxe longa e sem criação automática de caminhos ausentes. O preparador cria os caminhos antes da execução.
- As senhas de banco e a semente de sessão são arquivos locais usados como secrets. Apenas MySQL recebe a senha root; WordPress recebe a senha da aplicação e a semente de sessão.
- config/wordpress.php lê os valores em tempo de execução. As chaves de autenticação e salts são valores distintos derivados de uma semente aleatória persistente, compartilhados pelas três instâncias. A URL vem de SITE_URL.
- O script de início copia a distribuição WordPress presente na imagem oficial para a pasta compartilhada e inicia Apache. O arquivo de configuração é montado separadamente em modo somente leitura. Isso evita edições com sed no VirtioFS/APFS.
- MySQL usa emulação AMD64. WordPress e Nginx podem usar as variantes ARM64 disponíveis das tags indicadas.
- Nginx mantém a configuração principal da imagem; conf.d recebe o pool de três servidores, conexões HTTP persistentes, tempos limite e o cabeçalho X-Upstream. O balanceamento padrão é round-robin.
- A rede de persistência é interna. Nginx participa apenas da rede de requisições e publica somente 127.0.0.1:8086.

## Estado de validação

Foram aprovadas a resolução Compose, a conferência de cinco serviços e tags, isolamento de portas, redes, separação da senha root e sintaxe shell. O preparador foi reexecutado em pasta temporária para verificar preservação dos arquivos.

A execução foi aprovada em 15/10/2026: nginx -t, php -l, cinco serviços em execução, consulta às 12 tabelas, nove respostas HTTP 200, três destinos X-Upstream e conteúdo idêntico. O teste foi repetido após docker-compose stop e up -d, com aprovação. Capturas reais do terminal e da aplicação acompanham os JSONs.

O healthcheck do MySQL executa SELECT 1 autenticado no banco da aplicação, lendo a senha de arquivo. Isso confirma disponibilidade do banco utilizado pelo WordPress.

## Dependências e referências oficiais

Os arquivos de configuração não incorporam a distribuição WordPress, Nginx ou MySQL. As imagens oficiais continuam contendo seus próprios avisos de licença e autoria, que não foram alterados. Não é atribuída autoria exclusiva sobre essas tecnologias.

- Serviços Compose: https://docs.docker.com/reference/compose-file/services/
- Secrets Compose: https://docs.docker.com/reference/compose-file/secrets/
- Imagem WordPress: https://hub.docker.com/_/wordpress
- Imagem MySQL: https://hub.docker.com/_/mysql
- Configuração WordPress: https://developer.wordpress.org/advanced-administration/wordpress/wp-config/
- Upstream Nginx: https://nginx.org/en/docs/http/ngx_http_upstream_module.html
- Proxy Nginx: https://nginx.org/en/docs/http/ngx_http_proxy_module.html
- Cabeçalhos Nginx: https://nginx.org/en/docs/http/ngx_http_headers_module.html
