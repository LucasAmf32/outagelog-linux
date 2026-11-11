#!/bin/sh
# Installs OutageLog as a systemd service. Usage: sudo ./install.sh
# Instala o OutageLog como serviço do systemd. Uso: sudo ./install.sh
set -eu

case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in pt*) PT=1 ;; *) PT=0 ;; esac
msg() { if [ "$PT" = 1 ]; then echo "$1"; else echo "$2"; fi; }

if [ "$(id -u)" -ne 0 ]; then
    msg "Rode com sudo: sudo ./install.sh" "Run it with sudo: sudo ./install.sh" >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))'; then
    msg "Precisa do Python 3.8 ou mais novo (sudo apt install python3)." \
        "Python 3.8 or newer is required (sudo apt install python3)." >&2
    exit 1
fi

DIR=$(cd "$(dirname "$0")" && pwd)
LIB=/usr/local/lib/outagelog

msg "1/6 Copiando o programa para $LIB" "1/6 Copying the program to $LIB"
mkdir -p "$LIB"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp -r "$DIR/outagelog" "$TMP/"
find "$TMP" -name '__pycache__' -prune -exec rm -rf {} +
printf 'import sys\nfrom outagelog.cli import main\nsys.exit(main())\n' > "$TMP/__main__.py"
python3 -m zipapp "$TMP" -c -o "$LIB/outagelog.pyz"
chmod 0644 "$LIB/outagelog.pyz"

msg "2/6 Criando o comando /usr/local/bin/outagelog" "2/6 Creating the /usr/local/bin/outagelog command"
cat > /usr/local/bin/outagelog <<'SCRIPT'
#!/bin/sh
exec /usr/bin/env python3 -I /usr/local/lib/outagelog/outagelog.pyz "$@"
SCRIPT
chmod 0755 /usr/local/bin/outagelog

msg "3/6 Criando o usuário de sistema 'outagelog' (sem login, sem pasta pessoal)" \
    "3/6 Creating the 'outagelog' system user (no login, no home folder)"
if ! id outagelog >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin outagelog
fi

msg "4/6 Configuração em /etc/outagelog.ini" "4/6 Settings in /etc/outagelog.ini"
if [ -f /etc/outagelog.ini ]; then
    msg "    (já existe, mantida como está)" "    (already there, left as it is)"
else
    /usr/local/bin/outagelog config-exemplo > /etc/outagelog.ini
    chmod 0644 /etc/outagelog.ini
fi

msg "5/6 Ativando o serviço" "5/6 Starting the service"
install -m 0644 "$DIR/sistema/outagelog.service" /etc/systemd/system/outagelog.service
systemctl daemon-reload
systemctl enable outagelog >/dev/null 2>&1
systemctl restart outagelog

msg "6/6 Ícone na bandeja (avisa quando a internet cai)" "6/6 Tray icon (notifies you when the internet drops)"
TRAY=no
if python3 -I -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' >/dev/null 2>&1; then
    install -D -m 0644 "$DIR/sistema/outagelog.svg" /usr/local/share/icons/hicolor/scalable/apps/outagelog.svg
    install -D -m 0644 "$DIR/sistema/outagelog.desktop" /usr/local/share/applications/outagelog.desktop
    # Starts at every user's login (can be turned off in "Startup Applications").
    install -D -m 0644 "$DIR/sistema/outagelog.desktop" /etc/xdg/autostart/outagelog-bandeja.desktop
    gtk-update-icon-cache -q /usr/local/share/icons/hicolor >/dev/null 2>&1 || true
    TRAY=yes
else
    msg "    (sem GTK para Python: a bandeja não foi instalada; o serviço funciona normalmente)" \
        "    (no GTK for Python: tray icon not installed; the service works normally)"
fi

echo
if [ "$PT" = 1 ]; then
    echo "Pronto. O OutageLog está rodando e vai iniciar junto com o sistema."
    echo "  outagelog status            estado atual e quedas recentes"
    echo "  outagelog relatorio 7       relatório HTML dos últimos 7 dias"
    echo "  outagelog autoteste         confere se a detecção funciona nesta rede"
    echo "  journalctl -u outagelog -f  quedas aparecendo ao vivo no log do sistema"
    echo "  sudo nano /etc/outagelog.ini   (depois: sudo systemctl restart outagelog)"
    if [ "$TRAY" = yes ]; then
        echo
        echo "A bandeja abre sozinha no próximo login. Para abrir agora: menu > OutageLog"
        echo "(ou rode 'outagelog bandeja &' num terminal, sem sudo)."
    fi
else
    echo "Done. OutageLog is running and will start with the system."
    echo "  outagelog status            current state and recent outages"
    echo "  outagelog report 7          HTML report of the last 7 days"
    echo "  outagelog self-test         check that detection works on this network"
    echo "  journalctl -u outagelog -f  watch outages live in the system log"
    echo "  sudo nano /etc/outagelog.ini   (then: sudo systemctl restart outagelog)"
    if [ "$TRAY" = yes ]; then
        echo
        echo "The tray icon starts at your next login. To open it now: menu > OutageLog"
        echo "(or run 'outagelog tray &' in a terminal, without sudo)."
    fi
fi
