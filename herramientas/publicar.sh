#!/bin/bash
# Publica la app en GitHub Pages: sube la VERSION del service worker (si no, los celulares no se
# enteran del cambio), hace commit y push. GitHub la publica en 1-2 minutos y los celulares la bajan
# la proxima vez que abran la app con internet.
#   herramientas/publicar.sh "que cambio"
set -euo pipefail
cd "$(dirname "$0")/.."
msg="${1:?Uso: herramientas/publicar.sh \"descripcion del cambio\"}"
if git diff --quiet HEAD -- . ':!sw.js' && [ -z "$(git ls-files --others --exclude-standard)" ]; then
  echo "No hay cambios para publicar."; exit 1
fi
n=$(sed -n "s/^const VERSION = 'juando-\([0-9]*\)';/\1/p" sw.js)
sed -i "s/^const VERSION = 'juando-$n';/const VERSION = 'juando-$((n + 1))';/" sw.js
echo "version juando-$n -> juando-$((n + 1))"
git add -A
git commit -q -m "$msg"
git push -q
echo "Listo. En 1-2 minutos esta en https://facumos.github.io/juando/"
