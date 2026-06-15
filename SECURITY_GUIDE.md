# Руководство по безопасности и деплою

## Обзор

Этот проект использует защищённую single-server архитектуру с memory-only execution для защиты бизнес-логики от анализа.

## Режимы запуска

### Development Mode (без шифрования)
```bash
python main.py --dev
```
- Код не шифруется
- Защиты от отладки отключены
- Подходит для разработки и тестирования

### Production Mode (с шифрованием)
```bash
# Сначала зашифровать код
python build.py

# Запустить
python main.py
```
- Код шифруется AES-256-GCM
- Включены все защиты от отладки
- Ephemeral ключ генерируется при запуске
- Самоуничтожение при обнаружении угрозы

### Legacy Mode (обратная совместимость)
```bash
python main.py --legacy
```
- Старая архитектура без Runtime Engine
- Использует существующие handlers напрямую
- Подходит для постепенного миграции

## Процесс сборки (Build Process)

### 1. Шифрование кода
```bash
python build.py
```

Это создаст:
- `runtime/encrypted_core.py.enc` - зашифрованный код
- `runtime/runtime_key.bin` - ключ шифрования (временно)

### 2. Удаление ключа (security best practice)
```bash
python build.py --clean
```

Удаляет временные файлы сборки, включая ключ.

**ВАЖНО:** В production ключ должен быть уничтожен после запуска! Ключ генерируется автоматически при каждом запуске и живёт только в RAM.

## Безопасность

### Anti-Debug Protection

Система автоматически детектирует:
- gdb, strace, lldb
- TracerPid в /proc/self/status
- ptrace attachment
- Подозрительные родительские процессы

При обнаружении отладчика - самоуничтожение.

### Memory Protection

- Ephemeral ключ живёт только в RAM
- Код дешифруется только в памяти
- После выполнения данные очищаются
- Запрет core dumps

### Self-Destruction

При обнаружении угрозы:
1. Уничтожение ключей шифрования
2. Очистка чувствительных данных из памяти
3. Удаление временных файлов
4. Принудительное завершение процесса

## Система заказов

### Новые статусы
- `PENDING` - ожидает подтверждения администратором
- `CONFIRMED` - подтверждён администратором
- `COMPLETED` - выполнен
- `CANCELLED` - отменён

### Админ-подтверждение

**Логика:**
- Если ОДИН админ подтвердил заказ → статус `CONFIRMED`
- Второй админ НЕ обязан подтверждать
- Если второй админ подтверждает ПОСЛЕ → сообщение: "Заказ уже подтверждён"
- Atomic update для защиты от race conditions

**Защита от race conditions:**
```sql
BEGIN IMMEDIATE TRANSACTION
-- Проверка текущего статуса
-- Atomic update
COMMIT
```

### Кнопка "Мои заказы"

Добавлена в главное меню. Показывает:
- ⏳ Ожидающие подтверждения (PENDING)
- ✅ Подтверждённые (CONFIRMED)
- 📋 Другие статусы

## Структура проекта

```
mp/
├── relay/                      # Telegram Bot Layer (Relay)
│   ├── bot.py                  # aiogram bot initialization
│   └── dispatcher.py           # Request dispatcher to Runtime
├── runtime/                    # Runtime Engine (Core Logic)
│   ├── engine.py               # Main Runtime Engine
│   ├── loader.py               # Code loader & decryptor
│   ├── encrypted_core.py.enc   # Encrypted business logic
│   └── handlers/               # Business handlers
│       ├── order_handler.py    # Order logic with PENDING/CONFIRMED
│       ├── user_handler.py
│       └── product_handler.py
├── security/                   # Security Layer
│   ├── encryption.py           # AES-256-GCM encryption
│   ├── key_manager.py          # Ephemeral key management
│   ├── anti_debug.py           # Debugger detection
│   └── self_destruct.py       # Self-destruction mechanism
├── database.py                 # SQLite database
├── models.py                   # Data models
├── config.py                   # Configuration
├── main.py                     # Entry point
└── build.py                    # Build script for encryption
```

## Деплой на VPS

### 1. Подготовка сервера
```bash
# Установить зависимости
pip install -r requirements.txt

# Настроить .env
cp .env.example .env
nano .env  # Заполнить BOT_TOKEN и другие настройки
```

### 2. Сборка
```bash
# Зашифровать код
python build.py

# Удалить ключ (security)
python build.py --clean
```

### 3. Запуск
```bash
# Production mode
python main.py

# Или с systemd
sudo nano /etc/systemd/system/telegram-bot.service
```

### 4. Systemd service
```ini
[Unit]
Description=Telegram Bot with Runtime Engine
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/mp
ExecStart=/usr/bin/python3 main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable telegram-bot
sudo systemctl start telegram-bot
```

## Мониторинг

### Логи
```bash
# Просмотр логов
tail -f logs/bot.log

# Systemd logs
sudo journalctl -u telegram-bot -f
```

### Проверка статуса
```bash
sudo systemctl status telegram-bot
```

## Траблшутинг

### Ошибка "Зашифрованный файл не найден"
```bash
# Запустить build
python build.py
```

### Ошибка "Ключ шифрования не инициализирован"
- Убедитесь, что запускаете в production mode (без --dev)
- Проверьте, что файл encrypted_core.py.enc существует

### Ошибка "Обнаружен отладчик"
- Закройте gdb, strace, lldb
- Запустите без отладчика
- Для разработки используйте --dev флаг

### Бот не запускается
```bash
# Проверить .env
cat .env

# Проверить BOT_TOKEN
echo $BOT_TOKEN

# Запустить в legacy mode для тестирования
python main.py --legacy
```

## Безопасность в production

### ✅ DO
- Используйте production mode без --dev
- Удаляйте ключ после build.py
- Ограничьте доступ к серверу (firewall)
- Используйте HTTPS для webhook (если используется)
- Регулярно обновляйте зависимости
- Мониторьте логи на подозрительную активность

### ❌ DON'T
- Не храните ключ на диске в production
- Не запускайте с открытыми отладчиками
- Не передавайте зашифрованные файлы третьим лицам
- Не отключайте защиты в production
- Не используйте --dev в production

## Резервное копирование

### База данных
```bash
# Backup
cp data/database.db data/database.db.backup

# Restore
cp data/database.db.backup data/database.db
```

### Ключ шифрования
Ключ генерируется автоматически при запуске. Резервное копирование ключа НЕ требуется и НЕ рекомендуется.

## Обновление

### 1. Backup
```bash
# Backup базы данных
cp data/database.db data/database.db.backup.$(date +%Y%m%d)
```

### 2. Обновление кода
```bash
git pull
# или
# Скопировать новые файлы
```

### 3. Пересборка
```bash
python build.py
python build.py --clean
```

### 4. Перезапуск
```bash
sudo systemctl restart telegram-bot
```

## Поддержка

При проблемах:
1. Проверьте логи
2. Попробуйте legacy mode
3. Проверьте .env конфигурацию
4. Убедитесь, что все зависимости установлены
