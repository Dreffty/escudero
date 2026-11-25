#!/bin/zsh
# Instala (o actualiza) Escudero como una app normal de macOS:
#   ./instalar.sh
# Crea el entorno Python, empaqueta Escudero.app con py2app, la firma (ad-hoc),
# la deja en /Applications y la abre. Vive en la barra de menús (sin icono en el
# Dock) y se apunta sola a los ítems de inicio. Todo local: sin cuentas ni nube.
set -euo pipefail
cd "${0:A:h}"

# ── 1. Python 3.11+ (el de Homebrew o uno de python.org; el del sistema es 3.9) ──
PY=""
for c in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 \
         /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 \
         python3.13 python3.12 python3.11 python3; do
  p=$(command -v "$c" 2>/dev/null || true)
  [[ -n "$p" ]] || continue
  if "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$p"; break
  fi
done
if [[ -z "$PY" ]]; then
  echo "❌ Necesito Python 3.11 o más nuevo:  brew install python@3.12"
  exit 1
fi

# ── 2. Entorno y dependencias ──
# Si el venv se creó en otra carpeta (la moviste o renombraste), está roto: se rehace.
if [[ ! -x venv/bin/python ]] || ! venv/bin/python -m pip --version >/dev/null 2>&1; then
  echo "→ Creando entorno virtual con $PY…"
  rm -rf venv
  "$PY" -m venv venv
fi
echo "→ Instalando dependencias…"
venv/bin/python -m pip install -q --upgrade pip
venv/bin/python -m pip install -q -r requirements.txt py2app

# ── 3. Empaquetar ──
echo "→ Empaquetando Escudero.app (tarda un minuto)…"
rm -rf build dist
venv/bin/python setup.py -q py2app >/dev/null 2>&1
app="$PWD/dist/Escudero.app"
codesign --force --deep --sign - "$app"
codesign --verify --deep --strict "$app"

# ── 4. Tu config y tus datos: ~/Library/Application Support/Escudero ──
apoyo="$HOME/Library/Application Support/Escudero"
mkdir -p "$apoyo"
# Quien venía de la versión antigua (config.yaml y datos/ junto al código): se copian.
if [[ ! -f "$apoyo/config.yaml" && -f config.yaml ]]; then
  echo "→ Copiando tu config.yaml a $apoyo"
  cp config.yaml "$apoyo/config.yaml"
fi
if [[ ! -d "$apoyo/datos" && -d datos ]]; then
  echo "→ Copiando tus datos a $apoyo/datos (los originales se quedan en ./datos)"
  ditto datos "$apoyo/datos"
  rm -f "$apoyo/datos/escudero.lock"
fi

# ── 5. Retirar el autoarranque antiguo (abría start.command en Terminal) ──
viejo="$HOME/Library/LaunchAgents/com.escudero.mayordomo.plist"
if [[ -f "$viejo" ]]; then
  launchctl bootout "gui/$(id -u)/com.escudero.mayordomo" 2>/dev/null || true
  rm -f "$viejo"
  echo "→ Quitado el autoarranque antiguo por Terminal"
fi

# ── 6. Cerrar el Escudero en marcha e instalar ──
pkill -TERM -f "escudero\.py" 2>/dev/null || true
pkill -TERM -x Escudero 2>/dev/null || true
for _ in {1..20}; do
  if ! pgrep -f "escudero\.py" >/dev/null && ! pgrep -x Escudero >/dev/null; then break; fi
  sleep 0.5
done

if [[ -d "/Applications/Escudero.app" || -w "/Applications" ]]; then
  root="/Applications"
else
  root="$HOME/Applications"
fi
mkdir -p "$root"
target="$root/Escudero.app"
rm -rf "$target"
ditto "$app" "$target"
codesign --verify --deep --strict "$target"
/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -f "$target" 2>/dev/null || true

if [[ "${1:-}" != "--no-open" ]]; then
  open "$target"
fi

echo ""
echo "✅ Escudero instalado en $target"
echo "   Está en la barra de menús (🛡), no en el Dock, y se abrirá solo al iniciar sesión"
echo "   (se quita en su menú → «Abrir al iniciar sesión»)."
echo "   Tu configuración: $apoyo/config.yaml"
echo ""
echo "   Permisos (Ajustes → Privacidad y seguridad), para «Escudero»:"
echo "   · Accesibilidad — títulos de ventana en Crónica, Ventanas y pegar con ⏎."
echo "   · Grabación de pantalla — solo para Leer texto (⌃⌥T)."
echo "   Ordenar viene APAGADO: revisa las reglas y actívalo desde el menú."
