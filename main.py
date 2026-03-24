#!/usr/bin/env python3
import logging
import subprocess
import asyncio
import sqlite3
import re
import os
import glob
import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

API_TOKEN = "СЮДА_ТОКЕН_ТЕЛЕГРАМ_БОТА"
SERVICE_NAME = "pzserver.service"
ADMIN_CHAT_ID = СЮДА_ВАШ_ТЕЛЕГРАМ_ID_ИЛИ_ID_ЧАТА
PLAYERS_DB_PATH = "/root/Zomboid/Saves/Multiplayer/servertest/players.db"
USER_LOG_PATH = "/home/pzuser/Zomboid/Logs/*user.txt"
USERS_DB_FILE = "users_db.json"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

user_log_position = 0
recent_notifications = defaultdict(list)
last_seen_players = {}
ssh_failed_attempts = defaultdict(list)

USER_STATES = {}

class UserManager:
    def __init__(self, db_file=USERS_DB_FILE):
        self.db_file = db_file
        self.users = self.load_users()
    
    def load_users(self):
        try:
            if os.path.exists(self.db_file):
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки пользователей: {e}")
        return {}
    
    def save_users(self):
        try:
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(self.users, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения пользователей: {e}")
    
    def add_user(self, user_id, username="", full_name="", is_admin=False, is_banned=False):
        user_id = str(user_id)
        self.users[user_id] = {
            "username": username,
            "full_name": full_name,
            "is_admin": is_admin,
            "is_banned": is_banned,
            "added_date": datetime.now().isoformat()
        }
        self.save_users()
    
    def remove_user(self, user_id):
        user_id = str(user_id)
        if user_id in self.users:
            del self.users[user_id]
            self.save_users()
            return True
        return False
    
    def get_user(self, user_id):
        user_id = str(user_id)
        return self.users.get(user_id)
    
    def is_admin(self, user_id):
        user_id = str(user_id)
        user = self.users.get(user_id)
        return user.get("is_admin", False) if user else False
    
    def is_banned(self, user_id):
        user_id = str(user_id)
        user = self.users.get(user_id)
        return user.get("is_banned", False) if user else False
    
    def set_admin(self, user_id, is_admin=True):
        user_id = str(user_id)
        if user_id in self.users:
            self.users[user_id]["is_admin"] = is_admin
            self.save_users()
            return True
        return False
    
    def set_banned(self, user_id, is_banned=True):
        user_id = str(user_id)
        if user_id in self.users:
            self.users[user_id]["is_banned"] = is_banned
            self.save_users()
            return True
        return False
    
    def get_all_users(self):
        return self.users
    
    def get_user_count(self):
        return len(self.users)

user_manager = UserManager()

def get_latest_user_log():
    log_files = glob.glob(USER_LOG_PATH)
    if not log_files:
        return None
    
    latest_file = max(log_files, key=os.path.getmtime)
    return latest_file

def get_character_name(steam_id):
    try:
        conn = sqlite3.connect(PLAYERS_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM networkPlayers 
            WHERE name IS NOT NULL AND name != '' 
            ORDER BY id DESC LIMIT 1
        """)
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0]:
            return result[0].strip()
    except Exception as e:
        logger.error(f"Ошибка при чтении БД: {e}")
    
    return None

async def check_user_logs(bot):
    global user_log_position
    
    try:
        user_log_file = get_latest_user_log()
        if not user_log_file:
            return
        
        with open(user_log_file, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(user_log_position)
            lines = f.readlines()
            user_log_position = f.tell()
        
        for line in lines:
            line = line.strip()
            now = datetime.now()
            
            if "attempting to join" in line and "used queue" not in line:
                match = re.search(r'(\d+)\s+"([^"]+)"\s+attempting to join', line)
                if match:
                    steam_id = match.group(1)
                    steam_name = match.group(2)
                    
                    if steam_id in last_seen_players:
                        last_seen = last_seen_players[steam_id]["last_seen"]
                        if now - last_seen < timedelta(seconds=30):
                            continue
                    
                    character_name = get_character_name(steam_id)
                    last_seen_players[steam_id] = {
                        "name": steam_name,
                        "character": character_name,
                        "last_seen": now
                    }
                    
                    if character_name:
                        message = f"#Игроки_PZServer\n✅ Подключился игрок {character_name} ({steam_name})"
                    else:
                        short_id = steam_id[-8:]
                        message = f"#Игроки_PZServer\n✅ Подключился игрок {steam_name} (Steam ID: ...{short_id})"
                    
                    await bot.send_message(chat_id=ADMIN_CHAT_ID, text=message)
            
            elif "disconnected player" in line:
                match = re.search(r'(\d+)\s+"([^"]+)"\s+disconnected player', line)
                if match:
                    steam_id = match.group(1)
                    steam_name = match.group(2)
                    
                    if steam_id in last_seen_players:
                        last_seen = last_seen_players[steam_id]["last_seen"]
                        if now - last_seen < timedelta(seconds=10):
                            continue
                    
                    player_info = last_seen_players.get(steam_id, {})
                    character_name = player_info.get("character")
                    
                    if character_name:
                        message = f"#Игроки_PZServer\n❌ Отключился игрок {character_name} ({steam_name})"
                    else:
                        short_id = steam_id[-8:]
                        message = f"#Игроки_PZServer\n❌ Отключился игрок {steam_name} (Steam ID: ...{short_id})"
                    
                    await bot.send_message(chat_id=ADMIN_CHAT_ID, text=message)
                    last_seen_players[steam_id] = {
                        "name": steam_name,
                        "character": character_name,
                        "last_seen": now
                    }
    
    except Exception as e:
        logger.error(f"Ошибка при проверке user логов: {e}")

async def check_ssh_logs(bot):
    try:
        cmd = [
            "journalctl",
            "-u", "ssh",
            "--since", "1 minute ago",
            "--no-pager",
            "-o", "short"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            now = datetime.now()
            current_date = now.strftime('%Y-%m-%d')
            
            for line in result.stdout.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                if "Accepted" in line and ("password" in line or "publickey" in line):
                    ip_match = re.search(r'from\s+([0-9.:]+)', line)
                    user_match = re.search(r'for\s+(\S+)', line)
                    auth_method_match = re.search(r'Accepted\s+(\S+)\s+for', line)
                    
                    if ip_match:
                        ip = ip_match.group(1)
                        user = user_match.group(1) if user_match else "неизвестный"
                        auth_method = auth_method_match.group(1) if auth_method_match else "неизвестный"
                        
                        key = f"ssh_success_{ip}_{user}"
                        if key in recent_notifications:
                            recent_times = recent_notifications[key]
                            recent_times = [t for t in recent_times if now - t < timedelta(minutes=5)]
                            if recent_times:
                                continue
                            recent_notifications[key] = recent_times
                        else:
                            recent_notifications[key] = []
                        
                        recent_notifications[key].append(now)
                        
                        message = (
                            f"#SSH_Подключения\n"
                            f"✅ Успешное SSH подключение\n"
                            f"👤 Пользователь: {user}\n"
                            f"🔐 Метод аутентификации: {auth_method}\n"
                            f"🌐 IP адрес: {ip}\n"
                            f"📅 Дата: {current_date}\n"
                            f"🕒 Время: {now.strftime('%H:%M:%S')}"
                        )
                        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=message)
                
                elif "Failed password" in line:
                    ip_match = re.search(r'from\s+([0-9.:]+)', line)
                    user_match = re.search(r'for\s+(\S+)', line)
                    
                    if ip_match:
                        ip = ip_match.group(1)
                        user = user_match.group(1) if user_match else "unknown"
                        
                        password_match = re.search(r'Failed password for .* from .* port \d+ ssh2\s*(.*)$', line)
                        attempted_password = password_match.group(1).strip() if password_match else "пароль не найден в логе"
                        
                        if attempted_password == "пароль не найден в логе":
                            password_match = re.search(r'password\s+for\s+.*:\s+(.*)$', line)
                            attempted_password = password_match.group(1).strip() if password_match else "пароль не найден в логе"
                        
                        ssh_failed_attempts[ip].append(now)
                        ssh_failed_attempts[ip] = [
                            t for t in ssh_failed_attempts[ip]
                            if now - t < timedelta(minutes=10)
                        ]
                        
                        attempts_count = len(ssh_failed_attempts[ip])
                        
                        if attempts_count == 1 or attempts_count % 3 == 0:
                            key = f"ssh_failed_{ip}_{user}"
                            if key in recent_notifications:
                                recent_times = recent_notifications[key]
                                recent_times = [t for t in recent_times if now - t < timedelta(minutes=2)]
                                if recent_times:
                                    continue
                                recent_notifications[key] = recent_times
                            else:
                                recent_notifications[key] = []
                            
                            recent_notifications[key].append(now)
                            
                            password_display = attempted_password if attempted_password != "пароль не найден в логе" else "не удалось извлечь"
                            
                            if attempts_count > 1:
                                message = (
                                    f"#SSH_Подключения\n"
                                    f"🚨 Подозрительная активность SSH\n"
                                    f"❌ Неудачная попытка входа #{attempts_count}\n"
                                    f"👤 Пользователь: {user}\n"
                                    f"🔑 Введённый пароль: `{password_display}`\n"
                                    f"🌐 IP адрес: {ip}\n"
                                    f"📅 Дата: {current_date}\n"
                                    f"🕒 Время: {now.strftime('%H:%M:%S')}"
                                )
                            else:
                                message = (
                                    f"#SSH_Подключения\n"
                                    f"❌ Неудачное SSH подключение\n"
                                    f"👤 Пользователь: {user}\n"
                                    f"🔑 Введённый пароль: `{password_display}`\n"
                                    f"🌐 IP адрес: {ip}\n"
                                    f"📅 Дата: {current_date}\n"
                                    f"🕒 Время: {now.strftime('%H:%M:%S')}"
                                )
                            
                            await bot.send_message(chat_id=ADMIN_CHAT_ID, text=message, parse_mode='Markdown')
                
                elif "Invalid user" in line:
                    ip_match = re.search(r'from\s+([0-9.:]+)', line)
                    user_match = re.search(r'Invalid user\s+(\S+)', line)
                    
                    if ip_match:
                        ip = ip_match.group(1)
                        user = user_match.group(1) if user_match else "неизвестный"
                        
                        ssh_failed_attempts[ip].append(now)
                        ssh_failed_attempts[ip] = [
                            t for t in ssh_failed_attempts[ip]
                            if now - t < timedelta(minutes=10)
                        ]
                        
                        attempts_count = len(ssh_failed_attempts[ip])
                        
                        if attempts_count == 1 or attempts_count % 3 == 0:
                            key = f"ssh_failed_{ip}_{user}"
                            if key in recent_notifications:
                                recent_times = recent_notifications[key]
                                recent_times = [t for t in recent_times if now - t < timedelta(minutes=2)]
                                if recent_times:
                                    continue
                                recent_notifications[key] = recent_times
                            else:
                                recent_notifications[key] = []
                            
                            recent_notifications[key].append(now)
                            
                            if attempts_count > 1:
                                message = (
                                    f"#SSH_Подключения\n"
                                    f"🚨 Подозрительная активность SSH\n"
                                    f"❌ Неудачная попытка входа #{attempts_count}\n"
                                    f"👤 Неверный пользователь: {user}\n"
                                    f"🌐 IP адрес: {ip}\n"
                                    f"📅 Дата: {current_date}\n"
                                    f"🕒 Время: {now.strftime('%H:%M:%S')}"
                                )
                            else:
                                message = (
                                    f"#SSH_Подключения\n"
                                    f"❌ Неудачное SSH подключение\n"
                                    f"👤 Неверный пользователь: {user}\n"
                                    f"🌐 IP адрес: {ip}\n"
                                    f"📅 Дата: {current_date}\n"
                                    f"🕒 Время: {now.strftime('%H:%M:%S')}"
                                )
                            
                            await bot.send_message(chat_id=ADMIN_CHAT_ID, text=message)
                
                elif "authentication failure" in line:
                    ip_match = re.search(r'rhost=([0-9.:]+)', line)
                    user_match = re.search(r'user=(\S+)', line)
                    
                    if ip_match:
                        ip = ip_match.group(1)
                        user = user_match.group(1) if user_match else "unknown"
                        
                        ssh_failed_attempts[ip].append(now)
                        ssh_failed_attempts[ip] = [
                            t for t in ssh_failed_attempts[ip]
                            if now - t < timedelta(minutes=10)
                        ]
                        
                        attempts_count = len(ssh_failed_attempts[ip])
                        
                        if attempts_count == 1 or attempts_count % 3 == 0:
                            key = f"ssh_failed_{ip}_{user}"
                            if key in recent_notifications:
                                recent_times = recent_notifications[key]
                                recent_times = [t for t in recent_times if now - t < timedelta(minutes=2)]
                                if recent_times:
                                    continue
                                recent_notifications[key] = recent_times
                            else:
                                recent_notifications[key] = []
                            
                            recent_notifications[key].append(now)
                            
                            message = (
                                f"#SSH_Подключения\n"
                                f"❌ Ошибка аутентификации SSH\n"
                                f"👤 Пользователь: {user}\n"
                                f"🌐 IP адрес: {ip}\n"
                                f"📅 Дата: {current_date}\n"
                                f"🕒 Время: {now.strftime('%H:%M:%S')}"
                            )
                            
                            await bot.send_message(chat_id=ADMIN_CHAT_ID, text=message)
        
        else:
            cmd_alt = [
                "journalctl",
                "-u", "ssh.service",
                "--since", "1 minute ago",
                "--no-pager",
                "-o", "short"
            ]
            
            result_alt = subprocess.run(cmd_alt, capture_output=True, text=True, timeout=10)
            if result_alt.returncode == 0:
                pass
            
    except Exception as e:
        logger.error(f"Ошибка при проверке SSH логов: {e}")

async def monitor_logs(bot):
    while True:
        await check_user_logs(bot)
        await check_ssh_logs(bot)
        await asyncio.sleep(5)

def main_menu_keyboard(user_id):
    if user_manager.is_banned(user_id):
        return None
    
    keyboard = [
        [
            InlineKeyboardButton("Включить", callback_data='start_service'),
            InlineKeyboardButton("Выключить", callback_data='stop'),
        ],
        [
            InlineKeyboardButton("Перезагрузить", callback_data='restart'),
            InlineKeyboardButton("Статус сервера", callback_data='status'),
        ]
    ]
    
    if user_manager.is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👑 Доступ", callback_data='manage_users')])
    
    return InlineKeyboardMarkup(keyboard)

def back_button_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Назад", callback_data='back')]
    ])

def users_list_keyboard():
    users = user_manager.get_all_users()
    keyboard = []
    
    for user_id, user_data in users.items():
        username = user_data.get("username", "")
        full_name = user_data.get("full_name", "")
        is_admin = user_data.get("is_admin", False)
        is_banned = user_data.get("is_banned", False)
        
        status = ""
        if is_admin:
            status = "👑 "
        elif is_banned:
            status = "🚫 "
        
        display_name = full_name or username or f"ID: {user_id}"
        if len(display_name) > 20:
            display_name = display_name[:20] + "..."
        
        button_text = f"{status}{display_name}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f'user_{user_id}')])
    
    keyboard.append([InlineKeyboardButton("➕ Добавить", callback_data='add_user')])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='back')])
    
    return InlineKeyboardMarkup(keyboard)

def user_management_keyboard(user_id):
    user_data = user_manager.get_user(user_id)
    if not user_data:
        return back_button_keyboard()
    
    is_admin = user_data.get("is_admin", False)
    is_banned = user_data.get("is_banned", False)
    
    keyboard = []
    
    if is_banned:
        keyboard.append([InlineKeyboardButton("✅ Разбанить", callback_data=f'unban_{user_id}')])
    else:
        keyboard.append([InlineKeyboardButton("🚫 Забанить", callback_data=f'ban_{user_id}')])
    
    if is_admin:
        keyboard.append([InlineKeyboardButton("👤 Отобрать права админа", callback_data=f'remove_admin_{user_id}')])
    else:
        keyboard.append([InlineKeyboardButton("👑 Выдать права админа", callback_data=f'add_admin_{user_id}')])
    
    keyboard.append([InlineKeyboardButton("❌ Удалить пользователя", callback_data=f'delete_{user_id}')])
    keyboard.append([InlineKeyboardButton("ℹ️ Статус", callback_data=f'status_{user_id}')])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='manage_users')])
    
    return InlineKeyboardMarkup(keyboard)

def add_user_options_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚫 Забанить", callback_data='add_banned'),
            InlineKeyboardButton("👑 Админ", callback_data='add_admin')
        ],
        [
            InlineKeyboardButton("👤 Обычный пользователь", callback_data='add_regular'),
            InlineKeyboardButton("❌ Отмена", callback_data='manage_users')
        ]
    ])

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    
    if user_manager.is_banned(user_id):
        await update.message.reply_text("🚫 Нехер было злоупотреблять доверием.")
        return
    
    if not user_manager.get_user(user_id):
        is_admin = False
        if user_manager.get_user_count() == 0:
            is_admin = True
            await update.message.reply_text("🏆 Вы первый пользователь! Вам выданы права администратора.")
        
        user_manager.add_user(
            user_id=user_id,
            username=user.username or "",
            full_name=user.full_name or "",
            is_admin=is_admin,
            is_banned=False
        )
    
    await update.message.reply_text('УААААА', reply_markup=main_menu_keyboard(user_id))

async def control_server(action: str):
    try:
        subprocess.run(f"sudo systemctl {action} {SERVICE_NAME}", shell=True, check=True)
        return {
            "start": "Сервер PZ запущен.",
            "stop": "Сервер остановлен.",
            "restart": "Сервер перезагружен."
        }.get(action, "Действие выполнено.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка при выполнении команды {action}: {e}")
        return f"Ошибка при выполнении команды {action}."

async def status_server():
    try:
        result = subprocess.run(
            f"systemctl is-active {SERVICE_NAME}",
            shell=True,
            capture_output=True,
            text=True
        )
        status = result.stdout.strip()
        return "🟢 Сервер PZ активен." if status == "active" else f"Сервер {status}."
    except Exception as e:
        logger.error(f"Ошибка при проверке статуса: {e}")
        return "🔴 Сервер PZ не активен."

async def notify_admin(user, action, bot):
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        message = (
            f"#Лог_PZServer\n"
            f"👤 Пользователь: {user.full_name} (ID: {user.id})\n"
            f"🔘 Действие: {action}\n"
            f"🕒 Время: {now}"
        )
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=message)
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления админу: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_id = str(user.id)
    
    if user_manager.is_banned(user_id):
        await query.edit_message_text(
            text="🚫 Нехер было злоупотреблять доверием.",
            reply_markup=None
        )
        return
    
    action = query.data
    
    if action.startswith(('manage_users', 'user_', 'add_', 'ban_', 'unban_', 
                         'add_admin_', 'remove_admin_', 'delete_', 'status_')):
        if not user_manager.is_admin(user_id):
            await query.edit_message_text(
                text="❌ У вас нет прав для управления пользователями!",
                reply_markup=back_button_keyboard()
            )
            return
    
    if action != 'back' and not action.startswith(('add_', 'user_', 'ban_', 'unban_', 
                                                   'add_admin_', 'remove_admin_', 'delete_', 'status_')):
        await notify_admin(user, action, context.bot)
    
    if action == 'start_service':
        response = await control_server("start")
        markup = back_button_keyboard()
    
    elif action == 'stop':
        response = await control_server("stop")
        markup = back_button_keyboard()
    
    elif action == 'restart':
        response = await control_server("restart")
        markup = back_button_keyboard()
    
    elif action == 'status':
        response = await status_server()
        markup = back_button_keyboard()
    
    elif action == 'manage_users':
        users_count = user_manager.get_user_count()
        response = f"👥 Управление пользователями\nВсего пользователей: {users_count}"
        markup = users_list_keyboard()
    
    elif action.startswith('user_'):
        target_user_id = action.split('_')[1]
        user_data = user_manager.get_user(target_user_id)
        if user_data:
            full_name = user_data.get("full_name", "Не указано")
            username = user_data.get("username", "Не указано")
            is_admin = "👑 Администратор" if user_data.get("is_admin") else "👤 Пользователь"
            is_banned = "🚫 Забанен" if user_data.get("is_banned") else "✅ Активен"
            added_date = user_data.get("added_date", "Неизвестно")
            
            response = (
                f"👤 Пользователь: {full_name}\n"
                f"📱 Username: @{username}\n"
                f"🆔 ID: {target_user_id}\n"
                f"🎭 Статус: {is_admin}\n"
                f"📊 Состояние: {is_banned}\n"
                f"📅 Добавлен: {added_date}"
            )
        else:
            response = "❌ Пользователь не найден!"
        markup = user_management_keyboard(target_user_id)
    
    elif action == 'add_user':
        USER_STATES[user_id] = 'waiting_user_id'
        response = "Введите Telegram ID пользователя (только цифры):"
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data='manage_users')]])
    
    elif action in ['add_banned', 'add_admin', 'add_regular']:
        if user_id in USER_STATES and 'pending_user_id' in USER_STATES[user_id]:
            pending_user_id = USER_STATES[user_id]['pending_user_id']
            
            try:
                tg_user = await context.bot.get_chat(pending_user_id)
                username = tg_user.username or ""
                full_name = tg_user.full_name or ""
            except:
                username = ""
                full_name = ""
            
            is_banned = action == 'add_banned'
            is_admin = action == 'add_admin'
            
            user_manager.add_user(
                user_id=pending_user_id,
                username=username,
                full_name=full_name,
                is_admin=is_admin,
                is_banned=is_banned
            )
            
            status = "забаненным" if is_banned else "администратором" if is_admin else "пользователем"
            response = f"✅ Пользователь {full_name} (ID: {pending_user_id}) добавлен как {status}!"
            
            if user_id in USER_STATES:
                del USER_STATES[user_id]
            
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад к списку", callback_data='manage_users')]])
        else:
            response = "❌ Ошибка: данные пользователя не найдены!"
            markup = back_button_keyboard()
    
    elif action.startswith('ban_'):
        target_user_id = action.split('_')[1]
        if user_manager.set_banned(target_user_id, True):
            try:
                await context.bot.send_message(
                    chat_id=int(target_user_id),
                    text="🚫 Нехер было злоупотреблять доверием."
                )
            except:
                pass
            
            response = f"✅ Пользователь {target_user_id} забанен!"
        else:
            response = f"❌ Ошибка при бане пользователя {target_user_id}"
        markup = user_management_keyboard(target_user_id)
    
    elif action.startswith('unban_'):
        target_user_id = action.split('_')[1]
        if user_manager.set_banned(target_user_id, False):
            try:
                await context.bot.send_message(
                    chat_id=int(target_user_id),
                    text="✅ Вы были разбанены! Теперь вы снова можете использовать бота."
                )
            except:
                pass
            
            response = f"✅ Пользователь {target_user_id} разбанен!"
        else:
            response = f"❌ Ошибка при разбане пользователя {target_user_id}"
        markup = user_management_keyboard(target_user_id)
    
    elif action.startswith('add_admin_'):
        target_user_id = action.split('_')[2]
        if user_manager.set_admin(target_user_id, True):
            response = f"✅ Пользователь {target_user_id} теперь администратор!"
        else:
            response = f"❌ Ошибка при выдаче прав админа пользователю {target_user_id}"
        markup = user_management_keyboard(target_user_id)
    
    elif action.startswith('remove_admin_'):
        target_user_id = action.split('_')[2]
        if user_manager.set_admin(target_user_id, False):
            response = f"✅ У пользователя {target_user_id} отобраны права администратора!"
        else:
            response = f"❌ Ошибка при отборе прав админа у пользователя {target_user_id}"
        markup = user_management_keyboard(target_user_id)
    
    elif action.startswith('delete_'):
        target_user_id = action.split('_')[1]
        if user_manager.remove_user(target_user_id):
            response = f"✅ Пользователь {target_user_id} удален!"
            markup = users_list_keyboard()
        else:
            response = f"❌ Ошибка при удалении пользователя {target_user_id}"
            markup = user_management_keyboard(target_user_id)
    
    elif action.startswith('status_'):
        target_user_id = action.split('_')[1]
        user_data = user_manager.get_user(target_user_id)
        if user_data:
            full_name = user_data.get("full_name", "Не указано")
            username = user_data.get("username", "Не указано")
            is_admin = "👑 Администратор" if user_data.get("is_admin") else "👤 Пользователь"
            is_banned = "🚫 Забанен" if user_data.get("is_banned") else "✅ Активен"
            added_date = user_data.get("added_date", "Неизвестно")
            
            response = (
                f"📊 Статус пользователя:\n"
                f"👤 Имя: {full_name}\n"
                f"📱 @{username}\n"
                f"🆔 ID: {target_user_id}\n"
                f"🎭 Роль: {is_admin}\n"
                f"📈 Состояние: {is_banned}\n"
                f"📅 В системе с: {added_date}"
            )
        else:
            response = "❌ Пользователь не найден!"
        markup = user_management_keyboard(target_user_id)
    
    elif action == 'back':
        response = "Вы вернулись в главное меню:"
        markup = main_menu_keyboard(user_id)
    
    else:
        response = "Неизвестная команда"
        markup = main_menu_keyboard(user_id)
    
    await query.edit_message_text(text=response, reply_markup=markup)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    
    if user_manager.is_banned(user_id):
        await update.message.reply_text("🚫 Нехер было злоупотреблять доверием.")
        return
    
    text = update.message.text.strip()
    
    if user_id in USER_STATES and USER_STATES[user_id] == 'waiting_user_id':
        if text.isdigit():
            USER_STATES[user_id] = {'pending_user_id': text}
            
            await update.message.reply_text(
                "Выберите тип пользователя:",
                reply_markup=add_user_options_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ Неверный формат ID. Введите только цифры:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data='manage_users')]])
            )
    else:
        await update.message.reply_text(
            "Используйте кнопки для управления сервером.",
            reply_markup=main_menu_keyboard(user_id)
        )

async def main() -> None:
    application = Application.builder().token(API_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    logger.info("Бот запускается...")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    bot = application.bot
    asyncio.create_task(monitor_logs(bot))
    
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот останавливается...")
        await application.stop()
        await application.shutdown()

def run_bot():
    asyncio.run(main())

if __name__ == '__main__':
    run_bot()
