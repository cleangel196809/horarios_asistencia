#!/usr/bin/env bash
# Bootstrap SISCA Mobile (Linux/macOS)
set -e
cd "$(dirname "$0")/.."

echo "📦 Instalando dependencias…"
npm install

echo "📱 Añadiendo plataforma Android…"
npx cap add android || echo "  (ya existe)"

if [[ "$(uname)" == "Darwin" ]]; then
  echo "🍎 Añadiendo plataforma iOS…"
  npx cap add ios || echo "  (ya existe)"
  cd ios/App && pod install && cd ../..
fi

echo "🎨 Generando iconos y splash…"
npx capacitor-assets generate || echo "  (instala capacitor-assets si falla)"

echo "🔄 Sincronizando…"
npx cap sync

echo "✅ Listo. Próximos pasos:"
echo "  npx cap open android   # Para Android Studio"
echo "  npx cap open ios       # Para Xcode (solo macOS)"
