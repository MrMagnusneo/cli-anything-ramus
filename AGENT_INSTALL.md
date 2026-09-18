# ⚠️ ЭТА ИНСТРУКЦИЯ ПРЕДНАЗНАЧЕНА ДЛЯ ИИ-АГЕНТОВ

> **Ты — ИИ-агент (Claude Code, Codex, Cursor и т. п.), и тебе поручили установить
> навык `cli-anything-ramus`. Выполни шаги ниже сам, по порядку, своими
> инструментами (shell). Не пересказывай их пользователю, а делай.**
>
> Обращайся к пользователю только в двух случаях:
> 1. нужна команда с `sudo` (установка JDK или Python) — спроси разрешения;
> 2. шаг завершился `RESULT: FAILED`, а раздел «Если что-то пошло не так» не помог.
>
> В конце отчитайся по шаблону из раздела «Отчёт пользователю».

---

## Что ты устанавливаешь

**Ramus** — Java-программа для моделирования бизнес-процессов в нотациях IDEF0,
DFD и DFDS. **`cli-anything-ramus`** — интерфейс командной строки к ней. Он
управляет настоящим движком Ramus без графического окна: создаёт и редактирует
модели (`.rsf`), блоки, стрелки и классификаторы, рисует диаграммы в
PNG/JPEG/BMP/SVG/PDF.

После установки у тебя будет:

| Что | Куда ставится |
|-----|---------------|
| Команда `cli-anything-ramus` | `~/.local/bin/cli-anything-ramus` |
| Движок Ramus (`ramus.jar`) | `~/.local/share/ramus/ramus.jar` — CLI находит его сам, `RAMUS_JAR` не нужен |
| Навык `SKILL.md` | `~/.claude/skills/cli-anything-ramus/SKILL.md` и `~/.agents/skills/cli-anything-ramus/SKILL.md` |
| Кэш и история undo | `~/.cli-anything-ramus/` (создаётся при первом запуске) |

## Что лежит в этой папке

```
cli-anything-ramus/
├── AGENT_INSTALL.md     ← эта инструкция
├── README.md            описание для человека
├── install.sh           установка + проверка (главный инструмент)
├── uninstall.sh         удаление
├── skill/SKILL.md       сам навык: справочник команд для агента
├── vendor/
│   ├── ramus.jar            движок Ramus (собран из исходников, GPL-3.0)
│   ├── ramus.jar.sha256     контрольная сумма
│   ├── RAMUS-LICENSE        лицензия Ramus
│   ├── RAMUS-COMMIT         коммит, из которого собран jar
│   └── wheels/              пакет CLI и его зависимости — ставятся без сети
├── source/              исходники CLI (Python + Java-мост), тесты, RAMUS.md
└── examples/order_fulfilment.sh   рабочий пример модели
```

Сеть для установки **не нужна**: всё необходимое уже лежит в `vendor/`.

---

## Установка

### Шаг 0. Найди путь к этой папке

Все команды ниже используют переменную `BUNDLE` — абсолютный путь к папке, где
лежит этот файл.

```bash
BUNDLE=/home/x13/VScodeProjects/cli-anything-ramus   # замени, если папку перенесли
ls "$BUNDLE/install.sh" "$BUNDLE/vendor/ramus.jar"   # оба файла должны существовать
```

Если папку скопировали в другое место, используй новый путь. Скрипт сам
определяет, где он лежит, так что относительные пути не сломаются.

### Шаг 1. Проверь требования

Нужны **Python ≥ 3.10** и **JDK ≥ 11**. Именно JDK: нужен `javac`, одного JRE
недостаточно.

```bash
python3 --version
java -version
javac -version
```

**Если `javac` или `java` не найден**, установи JDK. Для этого нужен `sudo`, так
что **сначала спроси разрешения у пользователя**, затем выполни команду для его
системы:

| Система | Команда |
|---------|---------|
| Fedora / RHEL / CentOS | `sudo dnf install -y java-21-openjdk-devel` |
| Debian / Ubuntu | `sudo apt update && sudo apt install -y default-jdk` |
| Arch | `sudo pacman -S --needed jdk-openjdk` |
| macOS (Homebrew) | `brew install openjdk` (sudo не нужен) |

Систему можно определить так: `cat /etc/os-release` (Linux) или `uname -s` (macOS).

Если JDK установлен, но не в `PATH`, задай `export JAVA_HOME=/путь/к/jdk`.

### Шаг 2. Запусти установку

```bash
bash "$BUNDLE/install.sh"
```

Скрипт делает всё сам:

1. проверяет Python, `java` и `javac`;
2. сверяет контрольную сумму `ramus.jar` и копирует его в `~/.local/share/ramus/`;
3. ставит Python-пакет: сначала `pip install --user`, при отказе (например,
   PEP 668, «externally-managed-environment») — в отдельный venv
   `~/.local/share/cli-anything-ramus/venv` с симлинком в `~/.local/bin`;
4. кладёт `SKILL.md` в `~/.claude/skills/` и `~/.agents/skills/`, подставив в него
   путь к этой папке;
5. запускает `cli-anything-ramus doctor`: при первом запуске компилируется
   Java-мост, это 5–20 секунд;
6. **сквозной тест**: создаёт модель с 2 блоками и 2 стрелками, рисует её в PNG и
   PDF через настоящий Ramus и проверяет форматы файлов.

Скрипт идемпотентен, повторный запуск безопасен.

**Результат определяется по последней строке вывода:**

- `RESULT: OK` и код выхода `0` — всё установлено и работает, переходи к шагу 3;
- `RESULT: FAILED` и код выхода `1` — строка с `[FAIL]` объясняет причину и
  способ исправления. Исправь и запусти снова. См. «Если что-то пошло не так».

Полезные опции (`bash install.sh --help`):

| Опция | Когда нужна |
|-------|-------------|
| `--method venv` | pip `--user` запрещён или ломает системный Python |
| `--skills-dir DIR` | твой агент читает навыки из другого каталога; можно указать несколько раз |
| `--jar /path/ramus.jar` | использовать свою сборку Ramus вместо входящей в комплект |
| `--no-skill` | поставить только CLI, без SKILL.md |
| `--check` | ничего не менять, только проверить установку |

### Шаг 3. Убедись, что команда доступна по имени

Если в выводе был `[WARN] ... is not on PATH`, добавь `~/.local/bin` в `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"                          # текущая сессия
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc      # будущие сессии
```

Проверка:

```bash
cli-anything-ramus --version            # cli-anything-ramus, version 1.0.0
cli-anything-ramus --json doctor        # "available": true
```

### Шаг 4. Подключи навык

`install.sh` уже положил навык туда, где его ищут агенты:

| Агент | Где лежит навык |
|-------|-----------------|
| Claude Code | `~/.claude/skills/cli-anything-ramus/SKILL.md` |
| Агенты, читающие `~/.agents/skills` | `~/.agents/skills/cli-anything-ramus/SKILL.md` |
| Другой каталог навыков | `bash "$BUNDLE/install.sh" --skills-dir <каталог>` |
| Агент без системы навыков | просто прочитай `$BUNDLE/skill/SKILL.md` в контекст |

Список навыков обычно загружается при старте сессии, поэтому новый навык может
появиться только в следующей сессии. **Пока его нет в списке — прочитай
`~/.claude/skills/cli-anything-ramus/SKILL.md` напрямую:** это полный
справочник команд, и больше ничего для работы не нужно.

### Шаг 5. Финальная проверка

```bash
bash "$BUNDLE/install.sh" --check
```

Должна быть строка `RESULT: OK`. Это та же проверка, что в шаге 2 (doctor,
сквозной рендер, наличие SKILL.md), но без изменений в системе.

---

## Критерии успешной установки

Установка завершена, только если **все** пункты выполнены:

- [ ] `bash "$BUNDLE/install.sh" --check` заканчивается строкой `RESULT: OK`
- [ ] `cli-anything-ramus --json doctor` возвращает `"available": true`
- [ ] файл `~/.claude/skills/cli-anything-ramus/SKILL.md` существует и не содержит `{{BUNDLE_DIR}}`
- [ ] (если был WARN про PATH) `~/.local/bin` добавлен в `PATH`

---

## Если что-то пошло не так

| Сообщение | Что делать |
|-----------|------------|
| `python3 was not found` / `Python X is too old` | Установи Python ≥ 3.10 (нужен sudo — спроси пользователя) |
| `java was not found` | Установи JDK, см. шаг 1 |
| `javac was not found — a JRE is installed` | Стоит только JRE. Установи **JDK** (пакет `-devel` / `default-jdk`), см. шаг 1 |
| `java N is too old` | Нужен JDK 11+. Установи новый или укажи `JAVA_HOME` на него |
| `does not match vendor/ramus.jar.sha256` | Папка повреждена при копировании. Скопируй её заново |
| `pip install --user failed` + `externally-managed-environment` | Ничего делать не нужно: в режиме `auto` скрипт сам перейдёт на venv. Если ставил с `--method user`, запусти с `--method venv` |
| `Could not create a virtualenv` | Нет модуля venv: `sudo apt install -y python3-venv` (спроси пользователя), затем снова `install.sh` |
| `doctor reports the backend is not usable` | Прочитай поле `problem` в выводе, там точная причина. Чаще всего это `javac` не в `PATH` |
| `Failed to compile the Ramus bridge` | Проверь `javac -version` ≥ 11. Удали кэш `rm -rf ~/.cli-anything-ramus/bridge` и повтори |
| `Command failed: cli-anything-ramus ...` в сквозном тесте | Выполни ту же команду вручную с `--json` и прочитай поле `error` |
| `cli-anything-ramus: command not found` после успешной установки | `~/.local/bin` не в `PATH`, см. шаг 3 |

Если после двух попыток `RESULT: FAILED` остаётся, остановись и покажи
пользователю последние 30 строк вывода `install.sh`.

### Ручная установка (если `install.sh` запустить нельзя)

Те же действия по отдельности:

```bash
BUNDLE=/home/x13/VScodeProjects/cli-anything-ramus

# 1. движок
mkdir -p ~/.local/share/ramus
cp "$BUNDLE/vendor/ramus.jar" ~/.local/share/ramus/ramus.jar

# 2. CLI (без сети, из vendor/wheels)
python3 -m pip install --user --no-index --find-links "$BUNDLE/vendor/wheels" \
    "click>=8.0" "prompt-toolkit>=3.0"
python3 -m pip install --user --no-index --find-links "$BUNDLE/vendor/wheels" \
    --force-reinstall --no-deps "$BUNDLE"/vendor/wheels/cli_anything_ramus-*.whl

# 3. навык (с подстановкой пути к этой папке)
mkdir -p ~/.claude/skills/cli-anything-ramus
sed "s|{{BUNDLE_DIR}}|$BUNDLE|g" "$BUNDLE/skill/SKILL.md" \
    > ~/.claude/skills/cli-anything-ramus/SKILL.md

# 4. проверка
cli-anything-ramus --json doctor
```

---

## Отчёт пользователю

После успешной установки коротко сообщи пользователю:

```
Навык cli-anything-ramus установлен и проверен (install.sh --check → RESULT: OK).
- Команда: <путь из строки "CLI:" в Summary>
- Ramus:   ~/.local/share/ramus/ramus.jar
- Навык:   ~/.claude/skills/cli-anything-ramus/SKILL.md
- Способ установки: <pip --user | venv>
- Сквозной тест: модель создана, PNG и PDF отрисованы.
<если нужно:> ~/.local/bin добавлен в PATH в ~/.bashrc.
<если навык не виден в списке:> навык появится в новой сессии; до этого я читаю SKILL.md напрямую.
```

---

## Удаление

```bash
bash "$BUNDLE/uninstall.sh"                 # CLI, ramus.jar, навыки, кэш и история undo
bash "$BUNDLE/uninstall.sh" --keep-jar      # оставить ramus.jar
bash "$BUNDLE/uninstall.sh" --keep-state    # оставить историю undo и кэш моста
```

Файлы моделей (`.rsf`) и отрисованные диаграммы не удаляются. Зависимости
(`click`, `prompt-toolkit`, `wcwidth`) при установке через pip `--user` тоже
остаются: ими могут пользоваться другие программы.

## Что читать дальше

- **`skill/SKILL.md`** — как пользоваться CLI. Это главный документ для работы.
- `source/cli_anything/ramus/README.md` — полная документация CLI.
- `source/RAMUS.md` — как устроен Ramus и почему CLI сделан именно так.
- `examples/order_fulfilment.sh` — пример: двухуровневая IDEF0-модель от нуля до PDF.
