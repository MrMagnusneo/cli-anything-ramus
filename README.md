# cli-anything-ramus — пакет навыка

Самодостаточный комплект для установки навыка **`cli-anything-ramus`**: ИИ-агент
получает возможность работать с [Ramus](https://github.com/Vitaliy-Yakovchuk/ramus)
(моделирование бизнес-процессов в нотациях IDEF0 / DFD / DFDS) из командной строки.
Агент создаёт модели, блоки, стрелки и классификаторы и рисует диаграммы в
PNG/SVG/PDF. Всё это делает настоящий движок Ramus, запущенный без окна.

## Как отдать агенту

Скажи агенту:

> Прочитай `/home/x13/VScodeProjects/cli-anything-ramus/AGENT_INSTALL.md` и установи навык.

Инструкция написана для агента: он сам проверит требования, запустит
установку, проверит результат и отчитается. Спрашивать он будет только
разрешение на `sudo`, если в системе нет JDK.

## Установить самому

```bash
bash install.sh            # установка + сквозная проверка
bash install.sh --check    # только проверка
bash uninstall.sh          # удаление
```

Требования: Python 3.10+ и JDK 11+ (`java` и `javac`). Всё остальное лежит в
`vendor/`, сеть не нужна.

## Состав

| Путь | Что это |
|------|---------|
| `AGENT_INSTALL.md` | пошаговая инструкция для агента |
| `install.sh` / `uninstall.sh` | установка с проверкой / удаление |
| `skill/SKILL.md` | сам навык — справочник команд для агента |
| `vendor/ramus.jar` | движок Ramus, собранный из исходников (`./gradlew :local-client:shadowJar`) |
| `vendor/wheels/` | пакет CLI и его зависимости (`click`, `prompt-toolkit`, `wcwidth`) |
| `source/` | исходники CLI: Python, Java-мост, тесты (182 теста), `RAMUS.md` |
| `examples/order_fulfilment.sh` | пример: двухуровневая модель от нуля до PDF |

## Лицензия Ramus

`vendor/ramus.jar` — сборка Ramus, распространяемого по **GPL-3.0**
(`vendor/RAMUS-LICENSE`). Исходный код: <https://github.com/Vitaliy-Yakovchuk/ramus>,
коммит — в `vendor/RAMUS-COMMIT`. При передаче этого комплекта третьим лицам
передавай и эти файлы.
