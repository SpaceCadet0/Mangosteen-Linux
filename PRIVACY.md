# Privacy Policy — Mangosteen for Linux

*Last updated: 25 October 2026*

Mangosteen is a file converter and toolbox that runs entirely on your computer. It does not collect, send or share any
personal data.

## What Mangosteen does not do

- It does not connect to the internet. Conversions, tools, text recognition and background removal run on your device;
  no file, image, text or other content leaves your computer. The one exception is a download you start yourself: the
  optional background-removal model, fetched from its public address when you press the button for it.
- It has no accounts, no analytics, no advertising, no crash reporting and no tracking of any kind.
- It does not sell or share data with anyone, because it has none to share.

## What stays on your computer

Mangosteen keeps a few files for its own use in your user folders. They are never sent anywhere, and you can delete
them at any time:

- **Settings**: `~/.config/mangosteen/settings.json` — your language and options.
- **Recent results**: `~/.local/state/mangosteen/history.json` — the names and locations of the files Mangosteen
  created, the operation and the time, so the tray menu can show them. "Clear History" in the tray menu empties it.
- **Log**: `~/.local/state/mangosteen/mangosteen.log` — a technical record of what the app did, including the paths of
  files you worked with and errors, to help with troubleshooting. It stays on your computer unless you choose to attach
  it to a bug report yourself.
- **Helper files**: the optional background-removal model in `~/.local/share/mangosteen/models`, if you downloaded it.
- **Launcher and menu entries**, if you enable them in Settings: a `.desktop` entry, an autostart entry and the
  file managers' "Mangosteen" menu items (`~/.local/share/kio/servicemenus`, `~/.config/nemo/actions`, the Nautilus,
  Caja and Nemo script folders). Turning the option off removes them.

Results are saved next to your original files. Mangosteen never changes or deletes the originals; "Delete Result" moves
only a result to the trash.

## Mouse, keyboard and clipboard

To open its wheel while you drag files, Mangosteen asks the X server which keys and buttons are down while a drag is
in progress and watches for Shift, Ctrl or Alt (the keys you chose). It does not record what you type or your other
clicks; the local log notes only where the wheel opened and for which files. The clipboard is used only when you choose
"Copy" or "Path", to put the selected files or paths on it.

## Children

Mangosteen does not collect data from anyone, including children.

## Changes

If this policy changes, the new version will be published at this address with a new date.

## Contact

Questions about privacy: open an issue at https://github.com/SpaceCadet0/Mangosteen-Linux/issues

---

# Политика конфиденциальности — Mangosteen для Linux

*Обновлено: 25 октября 2026 года*

Mangosteen — конвертер файлов и набор инструментов, который полностью работает на вашем компьютере. Он не собирает,
не отправляет и не передаёт никакие персональные данные.

- Приложение не подключается к интернету. Конвертация, инструменты, распознавание текста и удаление фона выполняются на
  устройстве; файлы и их содержимое никуда не отправляются. Единственное исключение — загрузка, которую вы запускаете
  сами: необязательная модель для удаления фона скачивается по её открытому адресу, когда вы нажимаете соответствующую
  кнопку.
- Нет учётных записей, аналитики, рекламы, отчётов о сбоях и какого-либо отслеживания.
- В вашей домашней папке хранятся только настройки (`~/.config/mangosteen/settings.json`), список недавних результатов
  и технический журнал с путями к файлам (`~/.local/state/mangosteen/`), а также необязательная модель удаления фона
  (`~/.local/share/mangosteen/models`) и записи меню, если вы включили их в настройках. Они никуда не отправляются, их можно удалить в любой момент; историю
  очищает пункт «Очистить историю».
- Чтобы открыть колесо во время перетаскивания, Mangosteen узнаёт у X-сервера, какие клавиши нажаты, пока идёт
  перетаскивание, и реагирует на Shift, Ctrl или Alt (выбранные вами). Набираемый текст и остальные щелчки не
  записываются. Буфер обмена используется только для действий «Копировать» и «Путь».
- Оригиналы файлов никогда не меняются и не удаляются; «Удалить результат» отправляет в корзину только результат.

Вопросы: https://github.com/SpaceCadet0/Mangosteen-Linux/issues
