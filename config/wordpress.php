<?php
// Configuracao do experimento: valores privados sao lidos de arquivos locais.
function lerSegredoLaboratorio($arquivo) {
    $valor = @file_get_contents('/run/secrets/' . $arquivo);
    if ($valor === false || trim($valor) === '') {
        throw new RuntimeException('Segredo do laboratorio ausente: ' . $arquivo);
    }
    return trim($valor);
}

define('DB_HOST', 'database:3306');
define('DB_NAME', getenv('WP_DATABASE'));
define('DB_USER', getenv('WP_USER'));
define('DB_PASSWORD', lerSegredoLaboratorio('senha_aplicacao'));
define('DB_CHARSET', 'utf8mb4');
define('DB_COLLATE', '');

$semente = lerSegredoLaboratorio('semente_sessao');
foreach (array('AUTH_KEY', 'SECURE_AUTH_KEY', 'LOGGED_IN_KEY', 'NONCE_KEY',
               'AUTH_SALT', 'SECURE_AUTH_SALT', 'LOGGED_IN_SALT', 'NONCE_SALT') as $nome) {
    define($nome, hash_hmac('sha256', $nome, $semente));
}
unset($semente, $nome);

$table_prefix = 'wp_';
define('WP_HOME', getenv('SITE_URL'));
define('WP_SITEURL', getenv('SITE_URL'));
define('WP_DEBUG', false);
// O experimento preserva as versoes fixadas e nao agenda tarefas externas.
define('AUTOMATIC_UPDATER_DISABLED', true);
define('DISABLE_WP_CRON', true);

if (!defined('ABSPATH')) {
    define('ABSPATH', __DIR__ . '/');
}
require_once ABSPATH . 'wp-settings.php';
