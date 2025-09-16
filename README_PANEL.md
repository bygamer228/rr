# DutyBot — Веб‑панель (только панель)

## Быстрый старт (если бот уже в /opt/dutybot2)
```bash
scp panel_only.zip root@<IP>:/opt/
ssh root@<IP>
cd /opt
unzip panel_only.zip -d /opt/dutybot2   # распаковка в папку бота

cd /opt/dutybot2
. .venv/bin/activate
pip install -r requirements.txt

# .env можно не трогать, если уже есть. Иначе:
cp .env.example .env && nano .env
```

## Автозапуск
```bash
cp dutybot-panel.service /etc/systemd/system/dutybot-panel.service
systemctl daemon-reload
systemctl enable --now dutybot-panel
systemctl status dutybot-panel --no-pager
# если включён UFW:
ufw allow 8000/tcp
```

Открывайте панель: http://<IP>:8000 (пароль: ADMIN_PANEL_PASSWORD в .env).

> Панель использует файлы из той же папки: students.txt, schedule.json, start_date.txt, exceptions.json, debtors.json, sim_date.txt
> и при некоторых действиях делает `systemctl restart dutybot` (должен существовать сервис dutybot).
