#!/bin/bash
# ---------------------------------------------------------------------------
# Запуск приложения этикеток CNH одним действием.
#
#   scripts/launch.sh            запустить (с авто-обновлением из git)
#   scripts/launch.sh stop       остановить сервер
#   scripts/launch.sh restart    перезапустить
#   scripts/launch.sh status     показать состояние
#   scripts/launch.sh update     только обновиться, не запускать
#
# Ничего не ломает, если git/сеть недоступны: тогда просто запускается
# та версия, что уже лежит на диске.
# ---------------------------------------------------------------------------
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

LOGDIR="$ROOT/logs"; mkdir -p "$LOGDIR"
LOG="$LOGDIR/app.log"
PIDFILE="$LOGDIR/server.pid"
PORT="${LABEL_PORT:-8765}"
URL="http://127.0.0.1:$PORT/"

# Сообщения идут в stderr (stdout занят под возврат значений из функций)
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG" >&2; }

# --- вспомогательное: ждать процесс не дольше N секунд ---------------------
wait_pid() {                      # wait_pid <pid> <секунд>
    local pid="$1" limit="$2" i=0
    while kill -0 "$pid" 2>/dev/null; do
        if [ "$i" -ge $((limit * 2)) ]; then
            kill -9 "$pid" 2>/dev/null; return 1
        fi
        sleep 0.5; i=$((i + 1))
    done
    wait "$pid" 2>/dev/null
}

port_busy() { nc -z 127.0.0.1 "$PORT" >/dev/null 2>&1; }

server_pid() {
    [ -f "$PIDFILE" ] || return 1
    local pid; pid="$(cat "$PIDFILE" 2>/dev/null)"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && echo "$pid"
}

# --- 1. Обновление из git --------------------------------------------------
update() {
    [ -d "$ROOT/.git" ] || { log "git-репозитория нет — обновление пропущено"; return 0; }
    git -C "$ROOT" rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1 || {
        log "удалённый репозиторий не настроен — обновление пропущено"; return 0; }

    git -C "$ROOT" fetch --quiet >>"$LOG" 2>&1 &
    if ! wait_pid $! 20; then
        log "нет связи с git (таймаут 20 с) — работаем на текущей версии"
        return 0
    fi

    local before after
    before="$(git -C "$ROOT" rev-parse --short HEAD)"
    if git -C "$ROOT" merge --ff-only '@{u}' >>"$LOG" 2>&1; then
        after="$(git -C "$ROOT" rev-parse --short HEAD)"
        if [ "$before" != "$after" ]; then
            log "обновлено: $before -> $after"
        else
            log "обновление не требуется ($after)"
        fi
    else
        log "! обновиться не удалось (локальные правки или расхождение веток) —"
        log "  запускаем текущую версию $before; подробности в logs/app.log"
    fi
}

# --- 2. Python и зависимости ----------------------------------------------
ensure_python() {
    local venv="$ROOT/.venv" py="$ROOT/.venv/bin/python3" base
    base="$(command -v python3 || true)"

    if [ ! -x "$py" ]; then
        [ -n "$base" ] || { log "! Python 3 не найден. Установите его с python.org"; return 1; }
        log "создаю окружение .venv (один раз)"
        "$base" -m venv "$venv" >>"$LOG" 2>&1 || rm -rf "$venv"
    fi

    if [ -x "$py" ]; then
        local stamp="$ROOT/.deps-stamp" sum
        sum="$(shasum "$ROOT/requirements.txt" | awk '{print $1}')"
        if [ "$(cat "$stamp" 2>/dev/null)" != "$sum" ]; then
            log "ставлю зависимости (Pillow)"
            "$py" -m pip install --quiet --upgrade pip >>"$LOG" 2>&1
            if "$py" -m pip install --quiet -r "$ROOT/requirements.txt" >>"$LOG" 2>&1; then
                echo "$sum" >"$stamp"
            else
                log "! pip не смог поставить зависимости (нет сети?)"
            fi
        fi
        "$py" -c 'import PIL' >/dev/null 2>&1 && { echo "$py"; return 0; }
    fi

    # Запасной путь: системный python, если в нём уже есть Pillow.
    if [ -n "$base" ] && "$base" -c 'import PIL' >/dev/null 2>&1; then
        log "использую системный python3 (в .venv Pillow недоступен)"
        echo "$base"; return 0
    fi

    log "! Pillow недоступен ни в .venv, ни в системном python3"
    return 1
}

# --- 3. Старт / стоп -------------------------------------------------------
start() {
    if server_pid >/dev/null || port_busy; then
        log "уже запущено — открываю $URL"
        open "$URL"; return 0
    fi

    update
    local py; py="$(ensure_python)" || return 1

    log "старт: $py label_app/server.py"
    nohup "$py" "$ROOT/label_app/server.py" >>"$LOG" 2>&1 &
    echo $! >"$PIDFILE"

    local i=0
    while [ "$i" -lt 50 ]; do          # ждём порт до 25 секунд
        port_busy && { log "готово: $URL"; return 0; }
        server_pid >/dev/null || break
        sleep 0.5; i=$((i + 1))
    done

    rm -f "$PIDFILE"
    log "! сервер не поднялся, последние строки лога:"
    tail -n 15 "$LOG" >&2
    return 1
}

stop() {
    local pid; pid="$(server_pid)" && {
        kill "$pid" 2>/dev/null; sleep 1
        kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
        log "остановлено (pid $pid)"
    } || log "сервер не запущен"
    rm -f "$PIDFILE"
}

status() {
    local pid
    if pid="$(server_pid)"; then echo "работает, pid $pid, $URL"
    elif port_busy;         then echo "порт $PORT занят другим процессом"
    else                         echo "не запущено"; fi
    if git -C "$ROOT" rev-parse HEAD >/dev/null 2>&1; then
        echo "версия: $(git -C "$ROOT" log -1 --format='%h %ad %s' --date=short)"
    fi
}

case "${1:-start}" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; start ;;
    status)  status ;;
    update)  update ;;
    *) echo "использование: $0 [start|stop|restart|status|update]" >&2; exit 2 ;;
esac
