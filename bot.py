#!/usr/bin/env python3
"""
Casino Dice Bot for Render.com
"""

import json
import os
import random
import logging
import threading
from flask import Flask, render_template_string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

TOKEN = os.environ.get("TOKEN", "YOUR_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))
WEB_URL = os.environ.get("WEB_URL", "https://your-app.onrender.com")

PAYOUT_MULTIPLIER = 2
MAX_BET_UNITS = 3

bets = {}
round_active = False
mapping = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}
player_balances = {}
player_streaks = {}
FAIR_MODE = False
force_result = None
TARGET_WIN = None
TARGET_NUMBER = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DICE_FACES = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}

def save_data():
 try:
 data = {"balances": player_balances, "streaks": player_streaks, "mapping": mapping, "fair_mode": FAIR_MODE}
 with open("game_data.json", "w") as f:
 json.dump(data, f)
 except:
 pass

def load_data():
 global player_balances, player_streaks, mapping, FAIR_MODE
 try:
 if os.path.exists("game_data.json"):
 with open("game_data.json", "r") as f:
 data = json.load(f)
 player_balances = data.get("balances", {})
 player_streaks = data.get("streaks", {})
 mapping = data.get("mapping", {1:1,2:2,3:3,4:4,5:5,6:6})
 FAIR_MODE = data.get("fair_mode", False)
 except:
 pass

async def openbets(update: Update, context: ContextTypes.DEFAULT_TYPE):
 global round_active, bets
 if update.effective_user.id != ADMIN_ID:
 return
 round_active = True
 bets = {}
 await update.message.reply_text(" BETS OPEN!\n\nBet format: 3x5 = 3 units on 5\nMax 3 units per round")

async def viewbets(update: Update, context: ContextTypes.DEFAULT_TYPE):
 if update.effective_user.id != ADMIN_ID:
 return
 if not bets:
 await update.message.reply_text("No bets yet")
 return
 text = "BETS:\n"
 for uid, ub in bets.items():
 text += f"Player {uid}: "
 text += " | ".join([f"{u} on {n}" for n, u in ub.items()])
 text += f" (Total: {sum(ub.values())})\n"
 await update.message.reply_text(text)

async def setmap(update: Update, context: ContextTypes.DEFAULT_TYPE):
 global mapping
 if update.effective_user.id != ADMIN_ID:
 return
 if not context.args:
 await update.message.reply_text(f"Current: {mapping}\nUsage: /setmap 1>4 2>6 3>1 4>5 5>2 6>3")
 return
 try:
 new_map = {}
 for pair in context.args:
 k, v = pair.split(">")
 new_map[int(k)] = int(v)
 mapping = new_map
 save_data()
 await update.message.reply_text(f"Mapping: {mapping}")
 except:
 await update.message.reply_text("Error. Use: /setmap 1>4 2>6 3>1 4>5 5>2 6>3")

async def edge_fair(update, context):
 global mapping
 if update.effective_user.id != ADMIN_ID: return
 mapping = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}
 save_data()
 await update.message.reply_text("Edge: FAIR")

async def edge_low(update, context):
 global mapping
 if update.effective_user.id != ADMIN_ID: return
 mapping = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 5}
 save_data()
 await update.message.reply_text("Edge: LOW")

async def edge_mid(update, context):
 global mapping
 if update.effective_user.id != ADMIN_ID: return
 mapping = {1: 1, 2: 2, 3: 3, 4: 1, 5: 2, 6: 3}
 save_data()
 await update.message.reply_text("Edge: MID")

async def edge_high(update, context):
 global mapping
 if update.effective_user.id != ADMIN_ID: return
 mapping = {1: 3, 2: 3, 3: 3, 4: 4, 5: 4, 6: 4}
 save_data()
 await update.message.reply_text("Edge: HIGH")

async def fairmode(update: Update, context: ContextTypes.DEFAULT_TYPE):
 global FAIR_MODE
 if update.effective_user.id != ADMIN_ID: return
 FAIR_MODE = not FAIR_MODE if not context.args else context.args[0].lower() == "on"
 save_data()
 await update.message.reply_text(f"Fair Mode: {'ON' if FAIR_MODE else 'OFF'}")

async def forcewin(update: Update, context: ContextTypes.DEFAULT_TYPE):
 global force_result
 if update.effective_user.id != ADMIN_ID: return
 if not context.args:
 force_result = None
 await update.message.reply_text("Force cancelled")
 return
 force_result = int(context.args[0])
 await update.message.reply_text(f"Forced result: {force_result}")

async def letwin(update: Update, context: ContextTypes.DEFAULT_TYPE):
 global TARGET_WIN, TARGET_NUMBER
 if update.effective_user.id != ADMIN_ID: return
 if not context.args or context.args[0] == "off":
 TARGET_WIN, TARGET_NUMBER = None, None
 await update.message.reply_text("Target cancelled")
 return
 TARGET_WIN = context.args[0]
 TARGET_NUMBER = int(context.args[1]) if len(context.args) > 1 else None
 await update.message.reply_text(f"Player {TARGET_WIN} will win next round")

async def show_balances(update, context):
 if update.effective_user.id != ADMIN_ID: return
 if not player_balances:
 await update.message.reply_text("No balances")
 return
 text = "BALANCES:\n"
 for uid, bal in sorted(player_balances.items(), key=lambda x: x[1]):
 text += f"Player {uid}: {'+' if bal>=0 else ''}{bal}\n"
 await update.message.reply_text(text)

async def settle_cmd(update, context):
 global player_balances
 if update.effective_user.id != ADMIN_ID: return
 if len(context.args) < 2:
 await update.message.reply_text("Usage: /settle <user_id> <amount>")
 return
 uid, amount = context.args[0], int(context.args[1])
 player_balances[uid] = player_balances.get(uid, 0) - amount
 save_data()
 await update.message.reply_text(f"Settled. Balance: {player_balances[uid]}")

async def reset_cmd(update, context):
 global player_balances, player_streaks
 if update.effective_user.id != ADMIN_ID: return
 player_balances, player_streaks = {}, {}
 save_data()
 await update.message.reply_text("All data reset")

async def handle_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
 global bets, round_active
 if not round_active:
 return
 user_id = str(update.effective_user.id)
 user_name = update.effective_user.first_name
 text = update.message.text.strip().lower()
 parts = text.split()
 player_bets = {}
 total_units = 0
 try:
 for part in parts:
 if "x" not in part:
 await update.message.reply_text("Format: 3x5 or 1x2 2x4")
 return
 units, num = part.split("x")
 units, num = int(units), int(num)
 if num < 1 or num > 6:
 await update.message.reply_text("Number 1-6 only")
 return
 total_units += units
 player_bets[num] = player_bets.get(num, 0) + units
 if total_units > MAX_BET_UNITS:
 await update.message.reply_text(f"Max {MAX_BET_UNITS} units")
 return
 bets[user_id] = player_bets
 bet_desc = " | ".join([f"{u} on {n}" for n, u in player_bets.items()])
 await update.message.reply_text(f"{user_name}: {bet_desc} ({total_units} units)")
 except:
 await update.message.reply_text("Invalid format")

async def check_bal(update, context):
 bal = player_balances.get(str(update.effective_user.id), 0)
 await update.message.reply_text(f"Balance: {'+' if bal>=0 else ''}{bal}")

async def help_cmd(update, context):
 await update.message.reply_text("RULES:\n1. Admin opens bets\n2. Bet: 3x5 = 3 units on 5\n3. Win = 2x your bet\n\n/check - Your balance")

async def roll_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
 global force_result, TARGET_WIN, TARGET_NUMBER, FAIR_MODE, round_active
 if update.effective_user.id != ADMIN_ID:
 return
 if not round_active:
 await update.message.reply_text("Open bets first: /open")
 return
 if FAIR_MODE:
 anim_result = random.randint(1, 6)
 elif force_result is not None:
 anim_result = force_result
 force_result = None
 elif TARGET_WIN is not None:
 anim_result = TARGET_NUMBER if TARGET_NUMBER else (max(bets[TARGET_WIN], key=bets[TARGET_WIN].get) if TARGET_WIN in bets else random.randint(1, 6))
 TARGET_WIN, TARGET_NUMBER = None, None
 else:
 anim_result = random.randint(1, 6)
 game_result = anim_result if FAIR_MODE else mapping.get(anim_result, anim_result)
 animation_url = f"{WEB_URL}/roll/{anim_result}"
 keyboard = [
 [InlineKeyboardButton("OPEN DICE ANIMATION", url=animation_url)],
 [InlineKeyboardButton("CONFIRM & PROCESS", callback_data=f"confirm_{anim_result}_{game_result}")]
 ]
 markup = InlineKeyboardMarkup(keyboard)
 await update.message.reply_text(f"DICE ROLL READY!\n\n1. Click OPEN DICE ANIMATION\n2. Screen record the dice\n3. Send recording as proof\n4. Click CONFIRM & PROCESS\n\nAnimation shows: {DICE_FACES[anim_result]} {anim_result}\nResult: {game_result}", reply_markup=markup)

async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
 global round_active, bets, player_balances, player_streaks
 query = update.callback_query
 await query.answer()
 if query.from_user.id != ADMIN_ID:
 await query.edit_message_text("Only admin")
 return
 _, anim_result, game_result = query.data.split("_")
 anim_result = int(anim_result)
 game_result = int(game_result)
 if not bets:
 await query.edit_message_text("No bets")
 return
 results = f"DICE: {DICE_FACES[anim_result]} {anim_result}\nWINNER: {game_result}\n\n"
 total_payout = 0
 total_collected = 0
 for uid, ub in bets.items():
 total_bet = sum(ub.values())
 total_collected += total_bet
 if game_result in ub:
 won = ub[game_result]
 payout = won * PAYOUT_MULTIPLIER
 net = payout - total_bet
 player_balances[uid] = player_balances.get(uid, 0) + net
 total_payout += payout
 player_streaks[uid] = 0
 results += f"WIN: Player {uid}: +{payout}\n"
 else:
 player_balances[uid] = player_balances.get(uid, 0) - total_bet
 player_streaks[uid] = player_streaks.get(uid, 0) + 1
 results += f"LOST: Player {uid}: -{total_bet}\n"
 house = total_collected - (total_payout - total_collected)
 results += f"\nHOUSE: {'+' if house>=0 else ''}{house}"
 await query.edit_message_text(results)
 if player_balances:
 bal_text = "BALANCES:\n"
 for uid, bal in player_balances.items():
 bal_text += f"Player {uid}: {'+' if bal>=0 else ''}{bal}\n"
 await context.bot.send_message(chat_id=query.message.chat_id, text=bal_text)
 save_data()
 round_active = False
 bets = {}

async def status(update, context):
 if update.effective_user.id != ADMIN_ID: return
 await update.message.reply_text(f"STATUS\nFair: {'ON' if FAIR_MODE else 'OFF'}\nRound: {'OPEN' if round_active else 'CLOSED'}\nBets: {len(bets)}\nPlayers: {len(player_balances)}\nMapping: {mapping}")

flask_app = Flask(__name__)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
 <title>Dice Roll</title>
 <meta name="viewport" content="width=device-width, initial-scale=1.0">
 <style>
 * { margin: 0; padding: 0; box-sizing: border-box; }
 body {
 background: linear-gradient(135deg, #1a1a2e, #16213e);
 display: flex; justify-content: center; align-items: center;
 height: 100vh; font-family: Arial, sans-serif; overflow: hidden;
 }
 .container { text-align: center; cursor: pointer; }
 .scene { width: 200px; height: 200px; margin: 0 auto 50px; perspective: 600px; }
 .dice {
 width: 200px; height: 200px; position: relative;
 transform-style: preserve-3d; transition: transform 0.1s;
 }
 .dice.rolling {
 animation: roll 2.5s cubic-bezier(0.25, 0.1, 0.25, 1) forwards;
 }
 @keyframes roll {
 0% { transform: rotateX(0) rotateY(0) rotateZ(0); }
 30% { transform: rotateX(720deg) rotateY(540deg) rotateZ(360deg); }
 60% { transform: rotateX(1440deg) rotateY(1080deg) rotateZ(720deg); }
 100% { transform: rotateX({{rx}}deg) rotateY({{ry}}deg) rotateZ({{rz}}deg); }
 }
 .face {
 position: absolute; width: 200px; height: 200px;
 background: white; border: 4px solid #333; border-radius: 25px;
 display: flex; justify-content: center; align-items: center;
 box-shadow: inset 0 0 30px rgba(0,0,0,0.1);
 }
 .front { transform: translateZ(100px); }
 .back { transform: rotateY(180deg) translateZ(100px); }
 .right { transform: rotateY(90deg) translateZ(100px); }
 .left { transform: rotateY(-90deg) translateZ(100px); }
 .top { transform: rotateX(90deg) translateZ(100px); }
 .bottom { transform: rotateX(-90deg) translateZ(100px); }
 .dot { width: 30px; height: 30px; background: #222; border-radius: 50%; position: absolute; }
 .front .dot { top: 50%; left: 50%; transform: translate(-50%,-50%); }
 .right .dot:nth-child(1) { top: 20px; right: 20px; }
 .right .dot:nth-child(2) { bottom: 20px; left: 20px; }
 .top .dot:nth-child(1) { top: 20px; left: 20px; }
 .top .dot:nth-child(2) { top: 50%; left: 50%; transform: translate(-50%,-50%); }
 .top .dot:nth-child(3) { bottom: 20px; right: 20px; }
 .bottom .dot:nth-child(1) { top: 20px; left: 20px; }
 .bottom .dot:nth-child(2) { top: 20px; right: 20px; }
 .bottom .dot:nth-child(3) { bottom: 20px; left: 20px; }
 .bottom .dot:nth-child(4) { bottom: 20px; right: 20px; }
 .left .dot:nth-child(1) { top: 20px; left: 20px; }
 .left .dot:nth-child(2) { top: 20px; right: 20px; }
 .left .dot:nth-child(3) { top: 50%; left: 50%; transform: translate(-50%,-50%); }
 .left .dot:nth-child(4) { bottom: 20px; left: 20px; }
 .left .dot:nth-child(5) { bottom: 20px; right: 20px; }
 .back { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr 1fr; padding: 20px; }
 .back .dot { position: static; margin: auto; }
 .result {
 font-size: 80px; font-weight: bold; color: #FFD700;
 opacity: 0; transition: opacity 1s;
 text-shadow: 0 0 30px rgba(255,215,0,0.5);
 }
 .result.show { opacity: 1; }
 .hint { color: #aaa; margin-top: 20px; font-size: 18px; letter-spacing: 2px; }
 .hint.hidden { display: none; }
 </style>
</head>
<body>
 <div class="container" onclick="roll()">
 <div class="scene">
 <div class="dice" id="dice">
 <div class="face front"><div class="dot"></div></div>
 <div class="face back"><div class="dot"></div><div class="dot"></div><div class="dot"></div><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
 <div class="face right"><div class="dot"></div><div class="dot"></div></div>
 <div class="face left"><div class="dot"></div><div class="dot"></div><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
 <div class="face top"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
 <div class="face bottom"><div class="dot"></div><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
 </div>
 </div>
 <div class="result" id="result">{{target}}</div>
 <div class="hint" id="hint">TAP TO ROLL</div>
 </div>
 <script>
 const rotations = {1:[0,0,0],2:[0,-90,0],3:[-90,0,0],4:[90,0,0],5:[0,90,0],6:[0,180,0]};
 let done = false;
 function roll() {
 if(done) return;
 done = true;
 document.getElementById('dice').classList.add('rolling');
 document.getElementById('hint').classList.add('hidden');
 setTimeout(() => document.getElementById('result').classList.add('show'), 2300);
 }
 </script>
</body>
</html>
'''

@flask_app.route('/roll/<int:target>')
def roll_page(target):
 if target < 1 or target > 6:
 return "Invalid", 400
 rotations = {1: (0,0,0), 2: (0,-90,0), 3: (-90,0,0), 4: (90,0,0), 5: (0,90,0), 6: (0,180,0)}
 rx, ry, rz = rotations[target]
 return render_template_string(HTML_TEMPLATE, target=target, rx=rx, ry=ry, rz=rz)

@flask_app.route('/')
def home():
 return "Casino Dice Bot is running!"

def main():
 load_data()
 application = Application.builder().token(TOKEN).build()
 application.add_handler(CommandHandler("open", openbets))
 application.add_handler(CommandHandler("viewbets", viewbets))
 application.add_handler(CommandHandler("roll", roll_cmd))
 application.add_handler(CommandHandler("status", status))
 application.add_handler(CommandHandler("setmap", setmap))
 application.add_handler(CommandHandler("fair", fairmode))
 application.add_handler(CommandHandler("low", edge_low))
 application.add_handler(CommandHandler("mid", edge_mid))
 application.add_handler(CommandHandler("high", edge_high))
 application.add_handler(CommandHandler("forcewin", forcewin))
 application.add_handler(CommandHandler("letwin", letwin))
 application.add_handler(CommandHandler("balances", show_balances))
 application.add_handler(CommandHandler("settle", settle_cmd))
 application.add_handler(CommandHandler("reset", reset_cmd))
 application.add_handler(CommandHandler("check", check_bal))
 application.add_handler(CommandHandler("help", help_cmd))
 application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bet))
 application.add_handler(CallbackQueryHandler(confirm_callback, pattern="^confirm_"))
 threading.Thread(target=application.run_polling, kwargs={"allowed_updates": Update.ALL_TYPES}, daemon=True).start()
 logger.info("Bot started")

main()
