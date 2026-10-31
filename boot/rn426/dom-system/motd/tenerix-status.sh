# /etc/profile.d/tenerix-status.sh: login summary (temperatures, fan, network) for interactive shells.
case $- in *i*) ;; *) return 0 2>/dev/null || exit 0 ;; esac

_tx_hwmon() {
    for h in /sys/class/hwmon/hwmon*; do
        [ "$(cat "$h/name" 2>/dev/null)" = "$1" ] && { echo "$h"; return 0; }
    done
    return 1
}
_tx_c() { [ -r "$1" ] && echo "$(( $(cat "$1") / 1000 ))°C" || echo '?'; }

_tx_cpu=$(_tx_hwmon coretemp)
_tx_board=$(_tx_hwmon it8613)
_tx_cores=
_tx_pkg='?'
if [ -n "$_tx_cpu" ]; then
    for _tx_f in "$_tx_cpu"/temp*_input; do
        _tx_l=$(cat "${_tx_f%_input}_label" 2>/dev/null)
        case "$_tx_l" in
            Package*) _tx_pkg=$(_tx_c "$_tx_f") ;;
            Core*) _tx_cores="$_tx_cores
${_tx_l#Core } $(_tx_c "$_tx_f")" ;;
        esac
    done
    _tx_cores=$(echo "$_tx_cores" | sort -n | awk 'NF{printf " %s:%s", $1, $2}')
fi
_tx_mode=$(sed -n 's/.*mode=\([a-z]*\).*/\1/p' /run/tenerix-fan 2>/dev/null)
_tx_ip=$(ip -4 -o addr show scope global 2>/dev/null | awk '{printf "%s %s  ", $2, $4}')
_tx_up=$(awk '{d=int($1/86400); h=int($1%86400/3600); m=int($1%3600/60); printf "%dd %dh %dm", d, h, m}' /proc/uptime)
_tx_mem=$(awk '/MemTotal/{t=$2} /MemAvailable/{a=$2} END{printf "%d / %d MiB", (t-a)/1024, t/1024}' /proc/meminfo)
_tx_root=$(df -h / | awk 'NR==2{print $3 " / " $2 " (" $5 ")"}')
_tx_dom=$(df -h /media/dom 2>/dev/null | awk 'NR==2{print $4 " free"}')

printf '\n  \033[1mTenerix Zero\033[0m  %s  up %s\n' "$(hostname)" "$_tx_up"
printf '  ─────────────────────────────────────────────────────\n'
printf '  CPU      package %s   cores%s\n' "$_tx_pkg" "${_tx_cores:- ?}"
if [ -n "$_tx_board" ]; then
    printf '  Board    %s\n' "$(_tx_c "$_tx_board/temp2_input")"
    printf '  Fan      %s rpm   PWM %s/255   %s\n' "$(cat "$_tx_board/fan2_input" 2>/dev/null || echo '?')" \
        "$(cat "$_tx_board/pwm2" 2>/dev/null || echo '?')" "${_tx_mode:-keeper not running}"
else
    printf '  Board    it8613 not loaded (fan state unknown)\n'
fi
printf '  Network  %s\n' "${_tx_ip:-no IPv4 address}"
printf '  Memory   %s\n' "$_tx_mem"
printf '  Root     %s   DOM %s\n' "$_tx_root" "${_tx_dom:-?}"
[ "$_tx_mode" = emergency ] && printf '  \033[1;31m!! FAN EMERGENCY: full speed, see: logread | grep tenerix-fan\033[0m\n'
printf '  ─────────────────────────────────────────────────────\n'
printf '  temps = live sensors   settings: /etc/conf.d/tenerix-fan\n\n'
unset _tx_cpu _tx_board _tx_cores _tx_pkg _tx_mode _tx_ip _tx_up _tx_mem _tx_root _tx_dom _tx_f _tx_l
unset -f _tx_hwmon _tx_c 2>/dev/null
