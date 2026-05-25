import os
from datetime import datetime, timedelta
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient

# ================= CONFIGURATION =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['telegram_bot']

channels_col = db['channels']
users_col = db['users']

# ================= WELCOME / START =================
@bot.message_handler(commands=['start'])
def start_handler(message):
    args = message.text.split()
    if len(args) > 1:
        ch_id = args[1]
        try:
            ch_data = channels_col.find_one({"channel_id": int(ch_id)})
            if ch_data and 'plans' in ch_data:
                markup = InlineKeyboardMarkup()
                for mins, price in ch_data['plans'].items():
                    markup.add(InlineKeyboardButton(f"⏳ {mins} Min - ₹{price}", callback_data=f"paid_{ch_id}_{mins}"))
                bot.send_message(message.chat.id, f"👋 Welcome!\n\nSelect a subscription plan for *{ch_data['name']}*:", parse_mode="Markdown", reply_markup=markup)
                return
        except Exception as e:
            print(f"Error loading channel for user: {e}")
            
    bot.send_message(message.chat.id, "Welcome to the Subscription Management Bot! 🤖")

# ================= ADMIN CONFIGURATION FLOW =================
@bot.message_handler(commands=['add'])
def add_channel_start(message):
    if message.from_user.id != ADMIN_ID:
        return
    msg = bot.send_message(ADMIN_ID, "📥 Please forward a message from your target channel here, or send its Channel ID directly.")
    bot.register_next_step_handler(msg, process_channel_id)

def process_channel_id(message):
    try:
        if message.forward_from_chat:
            ch_id = message.forward_from_chat.id
            ch_name = message.forward_from_chat.title
        else:
            ch_id = int(message.text.strip())
            ch_name = "Private Channel"

        msg = bot.send_message(ADMIN_ID, f"📋 Channel found: *{ch_name}* ({ch_id})\n\nNow enter your pricing plans exactly in this format:\nMinutes:Price, Minutes:Price\n\nExample: 1440:99, 43200:199", parse_mode="Markdown")
        bot.register_next_step_handler(msg, finalize_channel, ch_id, ch_name)
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Failed to parse channel. Make sure it's an integer ID or a valid forward. Error: {e}")

def finalize_channel(message, ch_id, ch_name):
    try:
        raw_plans = message.text.split(',')
        plans_dict = {}
        for p in raw_plans:
            t, pr = p.strip().split(':')
            plans_dict[str(int(t))] = float(pr)

        channels_col.update_one(
            {"channel_id": int(ch_id)}, 
            {"$set": {"name": ch_name, "plans": plans_dict, "admin_id": ADMIN_ID}}, 
            upsert=True
        )
        bot_username = bot.get_me().username
        bot.send_message(ADMIN_ID, f"👥 *Setup Successful!*\n\nInvite Link for users:\nhttps://t.me/{bot_username}?start={ch_id}", parse_mode="Markdown")

    except Exception as e:
        print(f"Error in finalize_channel: {e}")
        bot.send_message(ADMIN_ID, "❌ Invalid format. Please use 'Min:Price, Min:Price'. Use /add to retry.")

# ================= USER PAYMENT FLOW =================
@bot.callback_query_handler(func=lambda call: call.data.startswith('paid_'))
def admin_notify(call):
    try:
        _, ch_id, mins = call.data.split('_')
        user = call.from_user
        ch_data = channels_col.find_one({"channel_id": int(ch_id)})
        price = ch_data['plans'][str(int(mins))]
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}_{ch_id}_{mins}"),
