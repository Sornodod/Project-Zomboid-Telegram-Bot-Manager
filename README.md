# Что это?
Это Telegram-бот, который:
1. Пишет кто присоеденился к серверу;
2. Пишет кто помер на сервере;
3. Имеет в себе кнопки "Включить"\"Выключить" сервер, а так же "Перезагрузить" и "Статус";
4. Выдача прав админа на бота вашим друзьям;
5. Бан доступа к боту ваших друзей, что злоупотребляли третьим пунктом;
6. Выдаёт админ доступ первому кто запустит бота!!! Так что тут внимательно.

# Установка
Копируем наш "чудо" проект бота в нужную (куда душа лежит) папку. По сути, нам нужен только файл main.py, а не весь репозиторий.
Обратите внимание на 16-ую и 18-ую строку в боте. Нам там нужно вписать токен и ID чата.
Пример:
```python
API_TOKEN = "869321781:83h3jJSN_G@!NNNNGFASSFWASD"
SERVICE_NAME = "pzserver.service"
ADMIN_CHAT_ID = -1057382758
PLAYERS_DB_PATH = "/root/Zomboid/Saves/Multiplayer/servertest/players.db"
USER_LOG_PATH = "/home/pzuser/Zomboid/Logs/*user.txt"
USERS_DB_FILE = "users_db.json"
```
Далее создаём виртуальное окружение:
```shell
python3 -m venv venv
```
Включаем его:
```shell
source venv/bin/activate
```
Устанавливаем бибилиотеку для Telegram:
```shell
pip install python-telegram-bot==20.7
```
Создаём скрипт для автозапуска всей этой истории:
```shell
nano run_bot.sh
```
```shell
#!/bin/bash
cd /root/pz-telegram-bot
source venv/bin/activate
python3 main.py
```
Даём ему права:
```shell
chmod +x run_bot.sh
```
Создаём службу для автозапуска:
```shell
sudo nano /etc/systemd/system/pz-telegram-bot.service
```
Пихуем туда это:
```ini
[Unit]
Description=Project Zomboid Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/pz-telegram-bot
ExecStart=/root/pz-telegram-bot/venv/bin/python3 /root/pz-telegram-bot/bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```
Перезапускаем systemd:
```shell
sudo systemctl daemon-reload
```
Врубаем новую службу в автозапуск:
```shell
sudo systemctl enable pz-telegram-bot
```
Запускаем её:
```shell
sudo systemctl start pz-telegram-bot
```
Чисто на всякий проверяем статус:
```shell
sudo systemctl status pz-telegram-bot
```
# P.S:
1. Токен для бота можно взять у @BotFather;
2. ID чата или ваш собственный можно узнать у @Getmyid_bot;
3. Я плохой программист. Программирование не моя профессия, а хобби. Так что, где-то что-то может быть криво, косо и баговоно. Прошу понять и простить.
