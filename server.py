import asyncio
import json
import os
import random
import time
import websockets

SAVE_FILE = "save.json"

players = {}
online = {}
chat_log = []

ADMIN_NICK = "cursed_pharaon"


def save_players():
    data = {"players": players, "chat_log": chat_log}
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_players():
    global players, chat_log
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            players = data.get("players", {})
            chat_log = data.get("chat_log", [])
            print(f"[СЕРВЕР] Загружено игроков: {len(players)}")
        except Exception as e:
            print(f"[СЕРВЕР] Ошибка загрузки: {e}")


def create_player(nick):
    return {
        "password": "",
        "dollars": 1000,
        "btc": 0.0,
        "level": 1,
        "exp": 0,
        "max_exp": 100,
        "plr_cpu": "",
        "plr_mat": "",
        "plr_gpu": [],
        "plr_bus": [],
        "mining_active": False,
        "is_admin": (nick == ADMIN_NICK),
    }


async def send(ws, msg):
    try:
        await ws.send(json.dumps(msg, ensure_ascii=False))
    except Exception:
        pass


async def broadcast(msg):
    if online:
        await asyncio.gather(*[send(ws, msg) for ws in list(online.keys())])


async def send_online_list():
    nicks = list(online.values())
    await broadcast({"type": "online", "players": nicks})


def get_bus_income(p):
    income = 0
    for b in p["plr_bus"]:
        income += {
            "шаурмечная": 10,
            "магазин": 12,
            "кофейня": 15,
            "кафе": 20,
            "заправка": 25,
            "сто": 30,
        }.get(b, 0)
    return income


async def tick_loop():
    while True:
        await asyncio.sleep(1)
        for nick, p in players.items():
            income = get_bus_income(p)
            if income > 0:
                p["dollars"] += income
                p["exp"] += random.randint(1, 3)
                while p["exp"] >= p["max_exp"]:
                    p["exp"] -= p["max_exp"]
                    p["level"] += 1
                    p["max_exp"] = int(p["max_exp"] * 1.15)


async def save_loop():
    while True:
        await asyncio.sleep(30)
        save_players()


async def handle_command(ws, nick, data):
    p = players[nick]
    cmd = data.get("cmd")

    if cmd == "chat":
        text = str(data.get("text", ""))[:200]
        if text.strip():
            msg = {"type": "chat", "from": nick, "text": text}
            chat_log.append(msg)
            if len(chat_log) > 100:
                chat_log.pop(0)
            await broadcast(msg)

    elif cmd == "online":
        await send(ws, {"type": "online", "players": list(online.values())})

    elif cmd == "state":
        await send(ws, {"type": "state", "data": p})

    elif cmd == "mine_on":
        if p["plr_cpu"] and p["plr_mat"] and p["plr_gpu"]:
            p["mining_active"] = True
            await send(ws, {"type": "info", "text": "Майнинг запущен"})
        else:
            await send(ws, {"type": "error", "text": "Сначала соберите риг"})

    elif cmd == "mine_off":
        p["mining_active"] = False
        await send(ws, {"type": "info", "text": "Майнинг остановлен"})

    elif cmd == "give":
        target = str(data.get("to", "")).strip()
        try:
            amount = int(data.get("amount", 0))
        except Exception:
            amount = 0
        if target not in players:
            await send(ws, {"type": "error", "text": "Игрок не найден"})
        elif target == nick:
            await send(ws, {"type": "error", "text": "Нельзя передать себе"})
        elif amount <= 0 or p["dollars"] < amount:
            await send(ws, {"type": "error", "text": "Недостаточно денег"})
        else:
            p["dollars"] -= amount
            players[target]["dollars"] += amount
            await send(ws, {"type": "info", "text": f"Передал {amount}$ игроку {target}"})
            for w, n in online.items():
                if n == target:
                    await send(w, {"type": "info", "text": f"{nick} передал вам {amount}$"})

    elif cmd == "buy":
        item = str(data.get("item", "")).lower()
        prices = {
            "celeron": 50, "pentium": 120, "core i3": 220,
            "basic board": 80, "standart board": 250, "pro board": 700,
            "gt 710": 100, "gtx 1050": 200, "gtx 1660": 400,
            "шаурмечная": 10000, "магазин": 15000, "кофейня": 18000,
            "кафе": 25000, "заправка": 30000, "сто": 35000,
        }
        if item not in prices:
            await send(ws, {"type": "error", "text": "Нет такого товара"})
            return
        price = prices[item]
        if p["dollars"] < price:
            await send(ws, {"type": "error", "text": "Недостаточно денег"})
            return
        mat_slots = {"basic board": 1, "standart board": 2, "pro board": 4}
        if item in ("celeron", "pentium", "core i3"):
            if p["plr_cpu"] == item:
                await send(ws, {"type": "error", "text": "Уже установлено"})
                return
            p["plr_cpu"] = item
        elif item in mat_slots:
            p["plr_mat"] = item
        elif item in ("gt 710", "gtx 1050", "gtx 1660"):
            if not p["plr_mat"]:
                await send(ws, {"type": "error", "text": "Сначала материнку"})
                return
            if len(p["plr_gpu"]) >= mat_slots[p["plr_mat"]]:
                await send(ws, {"type": "error", "text": "Нет слотов"})
                return
            p["plr_gpu"].append(item)
        elif item in ("шаурмечная", "магазин", "кофейня", "кафе", "заправка", "сто"):
            p["plr_bus"].append(item)
        p["dollars"] -= price
        p["exp"] += random.randint(1, 5)
        await send(ws, {"type": "info", "text": f"Куплено: {item} за {price}$"})

    elif cmd == "trade":
        target = str(data.get("to", "")).strip()
        amount = data.get("amount", 0)
        if target not in players or target == nick:
            await send(ws, {"type": "error", "text": "Неверный игрок"})
            return
        for w, n in online.items():
            if n == target:
                await send(w, {"type": "trade_offer", "from": nick, "amount": amount})
                await send(ws, {"type": "info", "text": f"Запрос отправлен {target}"})
                return
        await send(ws, {"type": "error", "text": "Игрок не в сети"})

    elif cmd == "admin":
        if not p.get("is_admin"):
            await send(ws, {"type": "error", "text": "Нет прав"})
            return
        action = data.get("action")
        if action == "give":
            target = data.get("to")
            amount = int(data.get("amount", 0))
            if target in players:
                players[target]["dollars"] += amount
                await send(ws, {"type": "info", "text": f"Выдал {amount}$ {target}"})
        elif action == "kick":
            target = data.get("to")
            for w, n in list(online.items()):
                if n == target:
                    await send(w, {"type": "error", "text": "Вас кикнул админ"})
                    await w.close()
        elif action == "list":
            await send(ws, {"type": "info", "text": f"Игроков: {len(players)}"})

    else:
        await send(ws, {"type": "error", "text": "Неизвестная команда"})


async def client_handler(ws, path=None):
    nick = None
    try:
        raw = await ws.recv()
        data = json.loads(raw)
        nick = str(data.get("nick", "")).strip()[:20]
        password = str(data.get("password", ""))[:50]

        if not nick:
            await send(ws, {"type": "error", "text": "Пустой ник"})
            return

        if nick in online.values():
            await send(ws, {"type": "error", "text": "Ник уже онлайн"})
            return

        if nick not in players:
            players[nick] = create_player(nick)
            players[nick]["password"] = password
            await send(ws, {"type": "info", "text": f"Добро пожаловать, {nick}!"})
        else:
            if players[nick]["password"] and players[nick]["password"] != password:
                await send(ws, {"type": "error", "text": "Неверный пароль"})
                return
            await send(ws, {"type": "info", "text": f"С возвращением, {nick}!"})

        online[ws] = nick
        print(f"[СЕРВЕР] {nick} подключился")

        await send(ws, {"type": "state", "data": players[nick]})
        await send(ws, {"type": "chat_history", "messages": chat_log})
        await send_online_list()

        async for raw in ws:
            try:
                data = json.loads(raw)
            except Exception:
                continue
            await handle_command(ws, nick, data)

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[СЕРВЕР] Ошибка: {e}")
    finally:
        if ws in online:
            del online[ws]
        if nick:
            print(f"[СЕРВЕР] {nick} отключился")
            await send_online_list()


async def main():
    load_players()
    asyncio.create_task(tick_loop())
    asyncio.create_task(save_loop())

    port = int(os.environ.get("PORT", 8765))
    print(f"[СЕРВЕР] Запуск на порту {port}")

    async with websockets.serve(client_handler, "0.0.0.0", port):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[СЕРВЕР] Сохранение...")
        save_players()
        print("[СЕРВЕР] Выход.")
