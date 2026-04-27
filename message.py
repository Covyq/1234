import os
import datetime
import traceback
import discord
from discord.ext import tasks
from peewee import *

# CONFIG
GUILD_ID = 1278259070666801214

ALLOWED_ROLE_IDS = [
    1493199914572972032,
    123456789012345678,
    987654321098765432,
    1477953756225081394,
    831242102179758100
]

bot = discord.Bot(intents=discord.Intents.all(), debug_guilds=[GUILD_ID])

db = SqliteDatabase("TimerDataBase.db")

CHANNEL_CACHE = {"sklad": {}, "simple": {}, "mpf": {}, "sklad_notify": {}}

# ================= DB =================

class BaseModel(Model):
    class Meta:
        database = db

class ChannelConfig(BaseModel):
    guild_id = BigIntegerField()
    channel_id = BigIntegerField()
    channel_type = TextField()

class Timer(BaseModel):
    guild_id = BigIntegerField()
    channel_id = BigIntegerField()
    message_id = BigIntegerField()
    text = TextField()
    time_end = BigIntegerField()
    author = BigIntegerField()
    kind = TextField(default="timer")

    boxes = IntegerField(null=True)
    taken_by = BigIntegerField(null=True)

    last_updated_by = BigIntegerField(null=True)
    last_updated_at = BigIntegerField(null=True)

    notified_3h = BooleanField(default=False)
    notified_2h_count = IntegerField(default=0)
    notified_1h_count = IntegerField(default=0)
    notification_messages = TextField(null=True)

db.connect(reuse_if_open=True)
db.create_tables([ChannelConfig, Timer])

# ================= CHANNELS =================

def load_channels():
    global CHANNEL_CACHE
    CHANNEL_CACHE = {"sklad": {}, "simple": {}, "mpf": {}, "sklad_notify": {}}
    for row in ChannelConfig.select():
        CHANNEL_CACHE[row.channel_type][row.guild_id] = row.channel_id

def set_channel(guild_id, channel_id, channel_type):
    row = ChannelConfig.get_or_none(
        (ChannelConfig.guild_id == guild_id) &
        (ChannelConfig.channel_type == channel_type)
    )

    if row:
        row.channel_id = channel_id
        row.save()
    else:
        ChannelConfig.create(
            guild_id=guild_id,
            channel_id=channel_id,
            channel_type=channel_type
        )

    CHANNEL_CACHE[channel_type][guild_id] = channel_id

def get_channel(guild_id, channel_type):
    return CHANNEL_CACHE.get(channel_type, {}).get(guild_id)

# ================= PERMS =================

def has_access(member):
    return member.guild_permissions.administrator or any(
        r.id in ALLOWED_ROLE_IDS for r in member.roles
    )

# ================= BUTTON HANDLER =================

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if not interaction.type == discord.InteractionType.component:
        return

    cid = interaction.data.get("custom_id")

    row = Timer.get_or_none(Timer.message_id == interaction.message.id)
    if not row:
        return

    # ===== СКЛАД =====

    if cid == "sklad_update":
        await interaction.response.defer()

        # удалить уведомления
        if row.notification_messages:
            notify_channel_id = get_channel(row.guild_id, "sklad_notify")
            channel = interaction.guild.get_channel_or_thread(notify_channel_id)

            for msg_id in row.notification_messages.split(","):
                try:
                    msg = await channel.fetch_message(int(msg_id))
                    await msg.delete()
                except:
                    pass

        row.notification_messages = None
        row.notified_3h = False
        row.notified_2h_count = 0
        row.notified_1h_count = 0

        now = datetime.datetime.now(datetime.timezone.utc)
        new_end = int((now + datetime.timedelta(hours=48)).timestamp())

        row.time_end = new_end
        row.last_updated_by = interaction.user.id
        row.last_updated_at = int(now.timestamp())
        row.save()

        await interaction.message.edit(
            content=f"{row.text}\n⏰ <t:{new_end}:R>",
            components=sklad_buttons()
        )

    if cid == "sklad_delete":
        await interaction.response.defer()
        if interaction.user.id != row.author:
            return
        row.delete_instance()
        await interaction.message.delete()

    # ===== TIMER =====

    if cid == "timer_delete":
        await interaction.response.defer()
        if interaction.user.id != row.author:
            return
        row.delete_instance()
        await interaction.message.delete()

    # ===== MPF =====

    if cid == "mpf_delete":
        await interaction.response.defer()
        if interaction.user.id != row.author:
            return
        row.delete_instance()
        await interaction.message.delete()

    if cid == "mpf_take":
        await interaction.response.defer()

        if row.taken_by:
            return await interaction.followup.send("❌ Уже забрали", ephemeral=True)

        row.taken_by = interaction.user.id
        row.save()

        await interaction.message.edit(
            content=interaction.message.content + f"\n📦 Забрал: {interaction.user.display_name}"
        )

# ================= BUTTONS =================

def sklad_buttons():
    return [
        discord.ui.ActionRow(
            discord.ui.Button(label="Обновить склад", style=1, custom_id="sklad_update"),
            discord.ui.Button(label="Удалить", style=4, custom_id="sklad_delete")
        )
    ]

def timer_buttons():
    return [
        discord.ui.ActionRow(
            discord.ui.Button(label="Удалить таймер", style=4, custom_id="timer_delete")
        )
    ]

def mpf_buttons():
    return [
        discord.ui.ActionRow(
            discord.ui.Button(label="Удалить", style=4, custom_id="mpf_delete"),
            discord.ui.Button(label="Забрал", style=1, custom_id="mpf_take")
        )
    ]

# ================= LOOP =================

@tasks.loop(seconds=30)
async def loop():
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    for t in Timer.select():

        if t.kind == "sklad":
            remaining = t.time_end - now

            if remaining > 0:
                sklad_name = t.text.splitlines()[3].replace("**Склад:** ", "")

                notify_text = f"@склад Ваш склад {sklad_name} скоро сгорит!"

                if remaining <= 10800 and not t.notified_3h:
                    await send_notify(t, notify_text)
                    t.notified_3h = True
                    t.save()

        if t.time_end < now:
            try:
                await process_expired_timer(t)
            except:
                print(traceback.format_exc())

# ================= UTILS =================

async def send_notify(t, text):
    cid = get_channel(t.guild_id, "sklad_notify")
    channel = bot.get_channel(cid)
    if not channel:
        return
    msg = await channel.send(text)

    ids = t.notification_messages.split(",") if t.notification_messages else []
    ids.append(str(msg.id))
    t.notification_messages = ",".join(ids)
    t.save()

async def process_expired_timer(t):
    guild = bot.get_guild(t.guild_id)
    channel = guild.get_channel_or_thread(t.channel_id)

    msg = await channel.fetch_message(t.message_id)

    if t.kind == "timer":
        await msg.edit(content=f"{t.text}\n✅", components=timer_buttons())

    if t.kind == "mpf":
        await msg.edit(content=f"{t.text}\n✅", components=mpf_buttons())

    if t.kind == "sklad":
        await msg.edit(content=f"{t.text}\n🔥 СГОРЕЛ")

    t.delete_instance()

# ================= READY =================

@bot.event
async def on_ready():
    print("Bot ready")
    load_channels()
    if not loop.is_running():
        loop.start()

# ================= COMMANDS =================

@bot.slash_command(name="setskladchannel", guild_ids=[GUILD_ID])
async def setskladchannel(ctx, sklad_channel: discord.TextChannel, notify_channel: discord.TextChannel):
    set_channel(ctx.guild.id, sklad_channel.id, "sklad")
    set_channel(ctx.guild.id, notify_channel.id, "sklad_notify")
    await ctx.respond("✅", ephemeral=True)

@bot.slash_command(name="setsimpletimer", guild_ids=[GUILD_ID])
async def setsimpletimer(ctx, channel: discord.TextChannel):
    set_channel(ctx.guild.id, channel.id, "simple")
    await ctx.respond("✅", ephemeral=True)

@bot.slash_command(name="setmpf", guild_ids=[GUILD_ID])
async def setmpf(ctx, channel: discord.TextChannel):
    set_channel(ctx.guild.id, channel.id, "mpf")
    await ctx.respond("✅", ephemeral=True)

@bot.slash_command(name="таймер", guild_ids=[GUILD_ID])
async def timer(ctx, название: str, minutes: int):
    end = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)).timestamp())

    msg = await ctx.send(
        f"{название}\n⏰ <t:{end}:R>",
        components=timer_buttons()
    )

    Timer.create(guild_id=ctx.guild.id, channel_id=ctx.channel.id,
                 message_id=msg.id, text=название, time_end=end,
                 author=ctx.author.id, kind="timer")

@bot.slash_command(name="мпф", guild_ids=[GUILD_ID])
async def mpf(ctx, что_поставил: str, ящиков: int, minutes: int):
    end = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)).timestamp())

    text = f"{что_поставил} ({ящиков})"

    msg = await ctx.send(text, components=mpf_buttons())

    Timer.create(guild_id=ctx.guild.id, channel_id=ctx.channel.id,
                 message_id=msg.id, text=text, time_end=end,
                 author=ctx.author.id, kind="mpf", boxes=ящиков)

@bot.slash_command(name="склад", guild_ids=[GUILD_ID])
async def sklad(ctx, гекс: str, регион: str, склад: str, пароль: str):
    end = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)).timestamp())

    text = f"{склад}\n{гекс} {регион} {пароль}"

    msg = await ctx.send(text, components=sklad_buttons())

    Timer.create(guild_id=ctx.guild.id, channel_id=ctx.channel.id,
                 message_id=msg.id, text=text, time_end=end,
                 author=ctx.author.id, kind="sklad")

# ================= RUN =================

bot.run(os.getenv("DISCORD_BOT_TOKEN"))
