#!/usr/bin/env bash
# Build the DeckForge desktop application on macOS or Linux.
#
#   ./packaging/build.sh              # build the app
#   ./packaging/build.sh --package    # ... and a .dmg (macOS) / AppImage (Linux)
#
# NOTE: this script has not been executed on macOS or Linux by the author; it
# mirrors the Windows pipeline, which is verified. Expect to adjust paths.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
PYTHON="$BACKEND/.venv/bin/python"
PACKAGE=0
SKIP_FRONTEND=0

for arg in "$@"; do
  case "$arg" in
    --package) PACKAGE=1 ;;
    --skip-frontend) SKIP_FRONTEND=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\n=== %s ===\n' "$1"; }

[ -x "$PYTHON" ] || { echo "no venv at $PYTHON — run: uv venv --python 3.14 backend/.venv"; exit 1; }

step "Installing backend, desktop and build dependencies"
# A `uv venv` has no pip in it, and that is the setup DEVELOPMENT.md documents.
if "$PYTHON" -m pip --version >/dev/null 2>&1; then
  "$PYTHON" -m pip install --disable-pip-version-check -q -e "$BACKEND[desktop,build]"
elif command -v uv >/dev/null 2>&1; then
  uv pip install --python "$PYTHON" -q -e "$BACKEND[desktop,build]"
else
  echo "neither pip nor uv is available for $PYTHON"; exit 1
fi

if [ "$SKIP_FRONTEND" -eq 0 ]; then
  step "Building the frontend"
  cd "$ROOT/frontend"
  [ -d node_modules ] || npm ci --no-audit --no-fund
  # Empty: the app is served by its own backend, so the API is same-origin.
  NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_API_URL="" npm run build
  cd "$ROOT"
fi

[ -f "$ROOT/frontend/out/index.html" ] || { echo "frontend/out/index.html missing"; exit 1; }

step "Generating the icon"
"$PYTHON" "$ROOT/packaging/make_icon.py"
if [ "$(uname)" = "Darwin" ]; then
  # PyInstaller's BUNDLE wants a real .icns.
  iconutil -c icns "$ROOT/packaging/assets/DeckForge.iconset" \
    -o "$ROOT/packaging/assets/icon.icns" || echo "iconutil failed; the app will use a default icon"
fi

step "Freezing with PyInstaller"
cd "$ROOT"
"$PYTHON" -m PyInstaller packaging/deckforge.spec --noconfirm --clean \
  --distpath "$ROOT/dist" --workpath "$ROOT/build"

if [ "$(uname)" = "Darwin" ]; then
  APP="$ROOT/dist/DeckForge.app"
  echo "Application: $APP"
  if [ "$PACKAGE" -eq 1 ]; then
    step "Creating the disk image"
    rm -f "$ROOT/dist/DeckForge.dmg"
    hdiutil create -volname DeckForge -srcfolder "$APP" -ov -format UDZO \
      "$ROOT/dist/DeckForge.dmg"
    echo "Disk image: $ROOT/dist/DeckForge.dmg"
    echo "Unsigned builds are quarantined by Gatekeeper. To distribute, sign and notarise:"
    echo "  codesign --deep --force --options runtime --sign 'Developer ID Application: …' '$APP'"
    echo "  xcrun notarytool submit dist/DeckForge.dmg --keychain-profile … --wait"
  fi
else
  APP="$ROOT/dist/DeckForge"
  echo "Application: $APP"
  if [ "$PACKAGE" -eq 1 ]; then
    step "Creating the AppImage"
    command -v appimagetool >/dev/null || {
      echo "appimagetool not found — see https://appimage.github.io/appimagetool/"; exit 1; }
    APPDIR="$ROOT/build/DeckForge.AppDir"
    rm -rf "$APPDIR"; mkdir -p "$APPDIR/usr/bin"
    cp -r "$APP"/* "$APPDIR/usr/bin/"
    cp "$ROOT/packaging/assets/icon.png" "$APPDIR/deckforge.png"
    cat > "$APPDIR/deckforge.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=DeckForge
Exec=DeckForge
Icon=deckforge
Categories=Office;Presentation;
Terminal=false
DESKTOP
    ln -sf usr/bin/DeckForge "$APPDIR/AppRun"
    appimagetool "$APPDIR" "$ROOT/dist/DeckForge-x86_64.AppImage"
    echo "AppImage: $ROOT/dist/DeckForge-x86_64.AppImage"
  fi
fi

printf '\nDone.\n'
