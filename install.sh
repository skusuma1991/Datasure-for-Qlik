#!/usr/bin/env bash
# DataSure Installer — Mac / Linux
# Usage:  bash install.sh
#         bash install.sh --no-setup    (skip wizard, just install)
set -euo pipefail

DATASURE_DIR="$HOME/.datasure"
VENV_DIR="$DATASURE_DIR/venv"
BIN_DIR="$HOME/.local/bin"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NO_SETUP=false

for arg in "$@"; do
  [[ "$arg" == "--no-setup" ]] && NO_SETUP=true
done

echo ""
echo "  ██████╗  █████╗ ████████╗ █████╗ ███████╗██╗   ██╗██████╗ ███████╗"
echo "  ██╔══██╗██╔══██╗╚══██╔══╝██╔══██╗██╔════╝██║   ██║██╔══██╗██╔════╝"
echo "  ██║  ██║███████║   ██║   ███████║███████╗██║   ██║██████╔╝█████╗  "
echo "  ██║  ██║██╔══██║   ██║   ██╔══██║╚════██║██║   ██║██╔══██╗██╔══╝  "
echo "  ██████╔╝██║  ██║   ██║   ██║  ██║███████║╚██████╔╝██║  ██║███████╗"
echo "  ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝"
echo ""
echo "  Analytics QA Platform  —  Installer"
echo ""

# ── check Python ──────────────────────────────────────────────────────────────
echo "→ Checking Python…"
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3; do
  if command -v "$cmd" &>/dev/null; then
    VER=$("$cmd" -c "import sys; print(sys.version_info[:2])")
    if "$cmd" -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" 2>/dev/null; then
      PYTHON="$cmd"
      echo "  Found: $PYTHON ($VER)"
      break
    fi
  fi
done

if [[ -z "$PYTHON" ]]; then
  echo ""
  echo "  ERROR: Python 3.10+ is required but not found."
  echo "  Install it from https://python.org/downloads or via your package manager."
  exit 1
fi

# ── create venv ───────────────────────────────────────────────────────────────
echo "→ Creating virtual environment at $VENV_DIR …"
mkdir -p "$DATASURE_DIR"
"$PYTHON" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# ── install package ───────────────────────────────────────────────────────────
echo "→ Installing DataSure…"
pip install --quiet --upgrade pip
pip install --quiet -e "$SCRIPT_DIR"

# ── create launcher script ────────────────────────────────────────────────────
echo "→ Creating launcher at $BIN_DIR/datasure …"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/datasure" <<EOF
#!/usr/bin/env bash
source "$VENV_DIR/bin/activate"
exec datasure "\$@"
EOF
chmod +x "$BIN_DIR/datasure"

# ── add to PATH if needed ─────────────────────────────────────────────────────
SHELL_RC=""
case "$SHELL" in
  */zsh)  SHELL_RC="$HOME/.zshrc" ;;
  */bash) SHELL_RC="$HOME/.bashrc" ;;
  */fish) SHELL_RC="$HOME/.config/fish/config.fish" ;;
esac

if [[ -n "$SHELL_RC" ]] && ! grep -q "$BIN_DIR" "$SHELL_RC" 2>/dev/null; then
  echo "" >> "$SHELL_RC"
  echo "# DataSure" >> "$SHELL_RC"
  echo "export PATH=\"\$PATH:$BIN_DIR\"" >> "$SHELL_RC"
  echo "  Added $BIN_DIR to PATH in $SHELL_RC"
fi

export PATH="$PATH:$BIN_DIR"

echo ""
echo "  ✓ DataSure installed successfully!"
echo ""

# ── run setup wizard ──────────────────────────────────────────────────────────
if [[ "$NO_SETUP" == "false" ]]; then
  echo "→ Launching setup wizard…"
  echo ""
  datasure setup
else
  echo "  Skipped setup. Run 'datasure setup' to configure your Qlik connection."
  echo ""
  echo "  Quick start:"
  echo "    datasure setup"
  echo "    datasure list-apps"
  echo "    datasure validate <APP_ID>"
fi
