import os
import datetime
import traceback
import discord
from discord.ext import tasks
from discord.ui import View, Button
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

    notify_stage = IntegerField(default=0)
    notify_messages = TextField(null=True)


db.connect(reuse_if_open=True)
db.create_tables([ChannelConfig, Timer])


# ================= CHANNELS =================

def load_channels():
    global CHANNEL_CACHE
    CHANNEL_CACHE = {"sklad": {}, "simple": {}, "mpf": {}, "sklad_notify": {}}

    for row in ChannelConfig.select():
        CHANNEL_CACHE.setdefault(row.channel_type, {})
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

    CHANNEL_CACHE.setdefault(channel_type, {})[guild_id] = channel_id


def get_channel(guild_id, channel_type):
    return CHANNEL_CACHE.get(channel_type, {}).get(guild_id)


# ================= PERMS =================

def has_access(member):
    return member.guild_permissions.administrator or any(
        r.id in ALLOWED_ROLE_IDS for r in member.roles
    )


# ================= CLEAN =================

def clean_channels():
    for row in ChannelConfig.select():
        guild = bot.get_guild(row.guild_id)
        if not guild or guild.get_channel_or_thread(row.channel_id) is None:
            row.delete_instance()


# ================= NOTIFY =================

async def delete_notifications(row, guild):
    if not row.notify_messages:
        return

    notify_channel_id = get_channel(row.guild_id, "sklad_notify")
    if not notify_channel_id:
        return

    channel = guild.get_channel(notify_channel_id)
    if not channel:
        return

    for mid in row.notify_messages.split(","):
        try:
            msg = await channel.fetch_message(int(mid))
            await msg.delete()
        except:
            pass

    row.notify_messages = None
    row.notify_stage = 0
    row.save()


async def handle_sklad_notifications(t):
    if t.kind != "sklad":
        return

    guild = bot.get_guild(t.guild_id)
    if not guild:
        return

    notify_channel_id = get_channel(t.guild_id, "sklad_notify")
    if not notify_channel_id:
        return

    channel = guild.get_channel(notify_channel_id)
    if not channel:
        return

    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    remaining = t.time_end - now

    sklad_name = t.text.splitlines()[3].replace("**Склад:** ", "")

    msg_text = (
        f"@склад Ваш склад {sklad_name} скоро сгорит!\n"
        f"Пожалуйста, обновите его в игре и обновите его в чате складов!"
    )

    async def send_and_save():
        msg = await channel.send(msg_text)

        ids = []
        if t.notify_messages:
            ids = list(map(int, t.notify_messages.split(",")))

        ids.append(msg.id)
        t.notify_messages = ",".join(map(str, ids))

    if remaining <= 3 * 3600 and t.notify_stage == 0:
        await send_and_save()
        t.notify_stage = 1

    elif remaining <= 2 * 3600 and t.notify_stage < 3:
        await send_and_save()
        t.notify_stage += 1

    elif remaining <= 3600 and t.notify_stage < 9:
        await send_and_save()
        t.notify_stage += 1

    t.save()


# ================= VIEWS =================

class SkladView(View):
    def __init__(self):
        super().__init__(timeout=None)

        btn_update = Button(label="Обновить склад", style=discord.ButtonStyle.green)
        btn_delete = Button(label="Удалить", style=discord.ButtonStyle.red)

        btn_update.callback = self.update
        btn_delete.callback = self.delete

        self.add_item(btn_update)
        self.add_item(btn_delete)

    async def update(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row:
            return

        await delete_notifications(row, interaction.guild)

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        new_end = int((now_dt + datetime.timedelta(hours=48)).timestamp())

        row.time_end = new_end
        row.last_updated_by = interaction.user.id
        row.last_updated_at = int(now_dt.timestamp())
        row.save()

        await interaction.message.edit(
            content=f"{row.text}\n⏰ До окончания: <t:{new_end}:R>",
            view=self
        )

    async def delete(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return

        await delete_notifications(row, interaction.guild)
        row.delete_instance()
        await interaction.message.delete()


class SkladExpiredView(View):
    def __init__(self):
        super().__init__(timeout=None)

        btn = Button(label="Удалить склад", style=discord.ButtonStyle.red)
        btn.callback = self.delete

        self.add_item(btn)

    async def delete(self, interaction):
        await interaction.response.defer()

        if not has_access(interaction.user):
            return

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if row:
            await delete_notifications(row, interaction.guild)
            row.delete_instance()

        await interaction.message.delete()


class TimerView(View):
    def __init__(self):
        super().__init__(timeout=None)

        btn = Button(label="Удалить таймер", style=discord.ButtonStyle.red)
        btn.callback = self.delete
        self.add_item(btn)

    async def delete(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return

        row.delete_instance()
        await interaction.message.delete()


class MPFView(View):
    def __init__(self, show_take=False):
        super().__init__(timeout=None)

        delete = Button(label="Удалить таймер", style=discord.ButtonStyle.red)
        delete.callback = self.delete
        self.add_item(delete)

        take = Button(label="Забрал заказ", style=discord.ButtonStyle.green, disabled=not show_take)
        take.callback = self.take
        self.add_item(take)

    async def take(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or row.taken_by:
            return

        row.taken_by = interaction.user.id
        row.save()

        await interaction.message.edit(
            content=interaction.message.content + f"\n📦 Забрал: {interaction.user.display_name}",
            view=self
        )

    async def delete(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return

        row.delete_instance()
        await interaction.message.delete()


# ================= LOOP =================

@tasks.loop(seconds=60)
async def loop():
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    for t in Timer.select():
        try:
            if t.time_end < now:
                continue
            await handle_sklad_notifications(t)
        except:
            print(traceback.format_exc())


# ================= READY =================

@bot.event
async def on_ready():
    print(f"Bot online {bot.user}")

    clean_channels()
    load_channels()

    bot.add_view(SkladView())
    bot.add_view(TimerView())
    bot.add_view(MPFView())
    bot.add_view(SkladExpiredView())

    if not loop.is_running():
        loop.start()


# ================= COMMANDS =================

@bot.slash_command(name="setskladchannel", guild_ids=[GUILD_ID])
async def setskladchannel(ctx, sklad_channel: discord.TextChannel, notify_channel: discord.TextChannel):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    set_channel(ctx.guild.id, sklad_channel.id, "sklad")
    set_channel(ctx.guild.id, notify_channel.id, "sklad_notify")

    await ctx.respond("✅ Каналы установлены", ephemeral=True)


@bot.slash_command(name="склад", guild_ids=[GUILD_ID])
async def sklad(ctx, гекс: str, регион: str, склад: str, пароль: str):
    channel_id = get_channel(ctx.guild.id, "sklad")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ не тот канал", ephemeral=True)

    await ctx.defer(ephemeral=True)

    end_ts = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)).timestamp())

    text = (
        f"👤 {ctx.author.display_name}\n"
        f"**Гекс:** {гекс}\n"
        f"**Регион:** {регион}\n"
        f"**Склад:** {склад}\n"
        f"**Пароль:** {пароль}"
    )

    msg = await ctx.send(
        f"{text}\n⏰ До окончания: <t:{end_ts}:R>",
        view=SkladView()
    )

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=text,
        time_end=end_ts,
        author=ctx.author.id,
        kind="sklad"
    )

    await ctx.followup.send("✅ склад создан", ephemeral=True)


# ================= RUN =================

bot.run(os.environ.get("DISCORD_BOT_TOKEN"))
