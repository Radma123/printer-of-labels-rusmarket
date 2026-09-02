# Запуск на macOS и авто-обновление

Как это устроено (коротко): код живёт в **закрытом git-репозитории**,
на каждом Mac лежит его клон, а сверху — тонкое приложение
**«Этикетки CNH.app»**. Двойной клик → приложение подтягивает свежую
версию из git → поднимает локальный сервер → открывает браузер.
Пересобирать приложение после обновлений не нужно: оно только запускает
`scripts/launch.sh`, а сам код обновляется через git.

Большой CSV (1.14 ГБ) и индекс `.pnidx` в git **не хранятся** (см.
`.gitignore`) — они переносятся между машинами вручную. GitHub не
принимает файлы больше 100 МБ, и версионировать гигабайт данных смысла нет.

---

## 1. Один раз: создать закрытый репозиторий

Локальный репозиторий уже создан (`git init`, ветка `main`).
Осталось привязать его к приватному репозиторию на GitHub.

Вариант А — через сайт: создать новый **private** репозиторий
(без README и .gitignore), затем:

```bash
cd ~/Downloads/printer-of-labels-rusmarket
git remote add origin git@github.com:ВАШ_ЛОГИН/printer-of-labels-rusmarket.git
git push -u origin main
```

Вариант Б — через GitHub CLI (`brew install gh`, затем `gh auth login`):

```bash
cd ~/Downloads/printer-of-labels-rusmarket
gh repo create printer-of-labels-rusmarket --private --source=. --remote=origin --push
```

Доступ по SSH настраивается один раз: `ssh-keygen -t ed25519`, затем ключ
`~/.ssh/id_ed25519.pub` добавить в GitHub → Settings → SSH keys.
При HTTPS вместо SSH пароль спросят один раз и он ляжет в Keychain.

## 2. Один раз: собрать приложение

```bash
bash scripts/build_app.sh
```

Появится `Этикетки CNH.app` в папке проекта и копия в `~/Applications`
(видна в Launchpad и Spotlight). Перетащите её в Dock.

При первом запуске macOS может спросить подтверждение — приложение
собрано локально, не подписано. Если Gatekeeper блокирует: правый клик по
иконке → «Открыть» → «Открыть».

## 3. Ежедневная работа

Просто клик по иконке в Dock. Дальше приложение само:

1. `git fetch` + `merge --ff-only` — если сети нет или GitHub недоступен,
   через 20 секунд молча запускается текущая версия;
2. проверяет `.venv` и Pillow (ставит при первом запуске);
3. поднимает сервер на `127.0.0.1:8765` и открывает браузер;
4. если сервер уже работает — просто открывает вкладку.

Полезные команды:

```bash
bash scripts/launch.sh status    # работает или нет, какая версия
bash scripts/launch.sh stop      # остановить сервер
bash scripts/launch.sh restart   # перезапустить
bash scripts/launch.sh update    # только обновиться
```

Лог запусков и ошибок: `logs/app.log`.

## 4. Выкатка изменений

С машины разработки:

```bash
git add -A && git commit -m "что изменил" && git push
```

На рабочих машинах новая версия приедет при следующем запуске приложения.
Если на рабочей машине кто-то правил файлы руками, `merge --ff-only`
откажется обновляться — в логе будет предупреждение, приложение запустится
на старой версии. Лечится `git checkout -- .` или `git stash`.

## 5. Установка на новый Mac

```bash
git clone git@github.com:ВАШ_ЛОГИН/printer-of-labels-rusmarket.git
cd printer-of-labels-rusmarket
bash scripts/build_app.sh
```

Плюс вручную, без git:

* скопировать `CNH_All_Parts_not-Full_20Cols.csv` в корень проекта
  (AirDrop, флешка, внешний диск);
* индекс `.pnidx` можно скопировать рядом с CSV или собрать заново
  кнопкой в приложении (~2 минуты);
* подключить принтер TSC TE200 как очередь CUPS `TSC_TE200`
  (драйвер и калибровка — см. `docs/current-state.md`).

Python 3 нужен только системный (python.org или Xcode CLT); Pillow
приложение ставит себе само в `.venv`.
