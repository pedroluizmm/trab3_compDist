<?php
// Cria os tres posts dos cenarios de carga usando a API do proprio WordPress.
// Executado dentro de um conteiner WordPress por scripts/preparar_cenarios.py.
// Idempotente: posts existentes (identificados pelo slug) sao reaproveitados.
// Tamanhos em unidades decimais: 1 MB = 1.000.000 bytes, 1 kB = 1.000 bytes.

chdir('/var/www/html');
require_once 'wp-load.php';
require_once ABSPATH . 'wp-admin/includes/image.php';
require_once ABSPATH . 'wp-admin/includes/file.php';
require_once ABSPATH . 'wp-admin/includes/media.php';

const TOLERANCIA = 0.02;

$CENARIOS = array(
    array('id' => 'imagem-1mb', 'slug' => 'cenario-1-imagem-1mb', 'tipo' => 'imagem',
          'alvo' => 1000000, 'semente' => 101, 'largura' => 1920, 'altura' => 1280,
          'titulo' => 'Cenario 1 - Post com imagem de aproximadamente 1 MB'),
    array('id' => 'texto-400kb', 'slug' => 'cenario-2-texto-400kb', 'tipo' => 'texto',
          'alvo' => 400000, 'semente' => 202,
          'titulo' => 'Cenario 2 - Post com texto de aproximadamente 400 kB'),
    array('id' => 'imagem-300kb', 'slug' => 'cenario-3-imagem-300kb', 'tipo' => 'imagem',
          'alvo' => 300000, 'semente' => 303, 'largura' => 1280, 'altura' => 853,
          'titulo' => 'Cenario 3 - Post com imagem de aproximadamente 300 kB'),
);

function desenhar_imagem($largura, $altura, $semente, $ruido) {
    mt_srand($semente);
    $img = imagecreatetruecolor($largura, $altura);
    // Fundo em gradiente, formas e ruido: conteudo fotografico sintetico e deterministico.
    for ($y = 0; $y < $altura; $y++) {
        $c = imagecolorallocate($img, (int)(40 + 150 * $y / $altura), 90, (int)(200 - 120 * $y / $altura));
        imageline($img, 0, $y, $largura - 1, $y, $c);
    }
    for ($i = 0; $i < 60; $i++) {
        $c = imagecolorallocatealpha($img, mt_rand(0, 255), mt_rand(0, 255), mt_rand(0, 255), mt_rand(30, 90));
        imagefilledellipse($img, mt_rand(0, $largura), mt_rand(0, $altura),
                           mt_rand(40, $largura / 3), mt_rand(40, $altura / 3), $c);
    }
    $pontos = (int)($largura * $altura * $ruido);
    for ($i = 0; $i < $pontos; $i++) {
        $c = imagecolorallocate($img, mt_rand(0, 255), mt_rand(0, 255), mt_rand(0, 255));
        imagesetpixel($img, mt_rand(0, $largura - 1), mt_rand(0, $altura - 1), $c);
    }
    return $img;
}

function jpeg_bytes($img, $qualidade) {
    ob_start();
    imagejpeg($img, null, $qualidade);
    return ob_get_clean();
}

// Busca binaria na quantidade de ruido (qualidade fixa) ate o tamanho alvo.
function gerar_jpeg($cen) {
    $baixo = 0.0;
    $alto = 1.0;
    $melhor = null;
    for ($passo = 0; $passo < 18; $passo++) {
        $ruido = ($baixo + $alto) / 2;
        $img = desenhar_imagem($cen['largura'], $cen['altura'], $cen['semente'], $ruido);
        $dados = jpeg_bytes($img, 85);
        imagedestroy($img);
        $erro = abs(strlen($dados) - $cen['alvo']) / $cen['alvo'];
        if ($melhor === null || $erro < $melhor[1]) {
            $melhor = array($dados, $erro);
        }
        if ($erro <= TOLERANCIA / 2) {
            break;
        }
        if (strlen($dados) < $cen['alvo']) {
            $baixo = $ruido;
        } else {
            $alto = $ruido;
        }
    }
    if ($melhor[1] > TOLERANCIA) {
        throw new RuntimeException('Imagem fora da tolerancia: ' . $cen['id']);
    }
    return $melhor[0];
}

function gerar_texto($alvo, $semente) {
    mt_srand($semente);
    $palavras = explode(' ', 'sistema distribuido carga usuario requisicao servidor instancia ' .
        'balanceamento resposta tempo desempenho conteiner banco dados rede latencia vazao ' .
        'experimento medicao processo memoria arquivo pagina conteudo navegador proxy aplicacao ' .
        'escalabilidade disponibilidade replicacao consistencia falha recuperacao cliente ' .
        'protocolo mensagem fila cache sessao recurso concorrencia paralelismo nucleo');
    $blocos = array();
    $total = 0;
    while ($total < $alvo) {
        $frases = array();
        for ($f = 0, $n = mt_rand(4, 8); $f < $n; $f++) {
            $frase = array();
            for ($p = 0, $m = mt_rand(8, 18); $p < $m; $p++) {
                $frase[] = $palavras[mt_rand(0, count($palavras) - 1)];
            }
            $frases[] = ucfirst(implode(' ', $frase)) . '.';
        }
        $bloco = "<!-- wp:paragraph -->\n<p>" . implode(' ', $frases) . "</p>\n<!-- /wp:paragraph -->\n\n";
        $blocos[] = $bloco;
        $total += strlen($bloco);
    }
    // Ajusta o ultimo paragrafo para aproximar o alvo sem cortar marcacao.
    $excesso = $total - $alvo;
    $ultimo = array_pop($blocos);
    $texto = substr($ultimo, strlen("<!-- wp:paragraph -->\n<p>"), -strlen("</p>\n<!-- /wp:paragraph -->\n\n"));
    $texto = rtrim(substr($texto, 0, max(1, strlen($texto) - $excesso)));
    $blocos[] = "<!-- wp:paragraph -->\n<p>" . $texto . "</p>\n<!-- /wp:paragraph -->\n";
    return implode('', $blocos);
}

function post_por_slug($slug) {
    $posts = get_posts(array('name' => $slug, 'post_type' => 'post', 'post_status' => 'any', 'numberposts' => 1));
    return $posts ? $posts[0] : null;
}

function bloco_imagem($anexo_id, $url, $alt) {
    return '<!-- wp:image {"id":' . $anexo_id . ',"sizeSlug":"full"} -->' . "\n" .
           '<figure class="wp-block-image size-full"><img src="' . esc_url($url) . '" alt="' . esc_attr($alt) .
           '" class="wp-image-' . $anexo_id . '"/></figure>' . "\n<!-- /wp:image -->\n";
}

wp_set_current_user(1);
$saida = array();
foreach ($CENARIOS as $cen) {
    $post = post_por_slug($cen['slug']);
    $criado = false;
    if ($post === null) {
        // Gera o conteudo antes de inserir: uma falha nao deixa post vazio para reuso.
        $jpeg = $cen['tipo'] === 'imagem' ? gerar_jpeg($cen) : null;
        $post_id = wp_insert_post(array(
            'post_title' => $cen['titulo'], 'post_name' => $cen['slug'], 'post_status' => 'publish',
            'post_author' => 1, 'post_content' => '',
        ), true);
        if (is_wp_error($post_id)) {
            throw new RuntimeException($post_id->get_error_message());
        }
        if ($cen['tipo'] === 'imagem') {
            $tmp = wp_tempnam($cen['slug'] . '.jpg');
            file_put_contents($tmp, $jpeg);
            $anexo_id = media_handle_sideload(array('name' => $cen['slug'] . '.jpg', 'tmp_name' => $tmp), $post_id);
            if (is_wp_error($anexo_id)) {
                throw new RuntimeException($anexo_id->get_error_message());
            }
            $conteudo = "<!-- wp:paragraph -->\n<p>Imagem do cenario de carga " . $cen['id'] .
                        ".</p>\n<!-- /wp:paragraph -->\n\n" .
                        bloco_imagem($anexo_id, wp_get_attachment_url($anexo_id), $cen['titulo']);
        } else {
            $conteudo = gerar_texto($cen['alvo'], $cen['semente']);
        }
        wp_update_post(array('ID' => $post_id, 'post_content' => $conteudo));
        $post = get_post($post_id);
        $criado = true;
    }
    $item = array(
        'cenario' => $cen['id'], 'slug' => $cen['slug'], 'post_id' => $post->ID, 'criado_agora' => $criado,
        'caminho' => '/?p=' . $post->ID, 'tamanho_conteudo_bytes' => strlen($post->post_content),
        'alvo_bytes' => $cen['alvo'], 'imagens' => array(),
    );
    if ($cen['tipo'] === 'imagem') {
        foreach (get_attached_media('image', $post->ID) as $anexo) {
            $arquivo = get_attached_file($anexo->ID);
            $url = wp_get_attachment_url($anexo->ID);
            $item['imagens'][] = array(
                'anexo_id' => $anexo->ID, 'caminho' => wp_parse_url($url, PHP_URL_PATH),
                'tamanho_bytes' => filesize($arquivo), 'sha256' => hash_file('sha256', $arquivo),
            );
        }
        $medido = $item['imagens'] ? $item['imagens'][0]['tamanho_bytes'] : 0;
    } else {
        $medido = $item['tamanho_conteudo_bytes'];
    }
    $item['desvio_alvo'] = round(($medido - $cen['alvo']) / $cen['alvo'], 4);
    $saida[] = $item;
}
echo json_encode($saida, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES), "\n";
