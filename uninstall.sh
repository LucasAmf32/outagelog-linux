#!/bin/sh
# Removes OutageLog. Logs and settings are kept unless you run: sudo ./uninstall.sh --all
# Remove o OutageLog. Os logs e a configuração são mantidos, a não ser com: sudo ./uninstall.sh --tudo
set -eu

case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in pt*) PT=1 ;; *) PT=0 ;; esac
msg() { if [ "$PT" = 1 ]; then echo "$1"; else echo "$2"; fi; }

if [ "$(id -u)" -ne 0 ]; then
    msg "Rode com sudo: sudo ./uninstall.sh" "Run it with sudo: sudo ./uninstall.sh" >&2
    exit 1
fi

systemctl disable --now outagelog >/dev/null 2>&1 || true
rm -f /etc/systemd/system/outagelog.service
systemctl daemon-reload >/dev/null 2>&1 || true
rm -f /usr/local/bin/outagelog
rm -f /etc/xdg/autostart/outagelog-bandeja.desktop /usr/local/share/applications/outagelog.desktop
rm -f /usr/local/share/icons/hicolor/scalable/apps/outagelog.svg
pkill -f "outagelog.pyz (bandeja|tray)" 2>/dev/null || true
rm -rf /usr/local/lib/outagelog

case "${1:-}" in
    --all|--tudo)
        rm -rf /var/lib/outagelog /var/lib/private/outagelog
        rm -f /etc/outagelog.ini
        if id outagelog >/dev/null 2>&1; then userdel outagelog; fi
        msg "OutageLog removido, junto com os logs e a configuração." "OutageLog removed, along with its logs and settings."
        ;;
    *)
        msg "OutageLog removido. Os logs continuam em /var/lib/outagelog e a configuração em /etc/outagelog.ini." \
            "OutageLog removed. Logs are still in /var/lib/outagelog and settings in /etc/outagelog.ini."
        msg "Para apagar tudo: sudo ./uninstall.sh --tudo" "To delete everything: sudo ./uninstall.sh --all"
        ;;
esac
