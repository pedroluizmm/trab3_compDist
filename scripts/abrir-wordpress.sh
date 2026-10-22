#!/bin/sh
set -eu

destino=/var/www/html
if [ ! -f "$destino/wp-includes/version.php" ]; then
    cp -R /usr/src/wordpress/. "$destino/"
fi
cd "$destino"
exec apache2-foreground
