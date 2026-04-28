# discord_bot_ready_single_file.py
# Готовый один файл для Discord-бота.
# ВАЖНО: токен бота НЕ храни в .txt и НЕ заливай на GitHub.
# Добавь токен в переменную окружения DISCORD_BOT_TOKEN или в Secrets на хостинге.

import os
import datetime
import traceback
import logging

import discord
from discord.ext import tasks
from discord.ui import View, Button
from peewee import *


# =========================
# НАСТРОЙКИ
# =========================
GUILD_ID = 1494712012314509372

# Роли, которым доступны команды настройки бота и удаление активностей
ALLOWED_ROLE_IDS = [
    1493199914572972032,
    123456789012345678,
    987654321098765432,
    1477953756225081394,
    831242102179758100,
]

# Отдельные роли, которым можно создавать активности командой /активность
# Впиши сюда нужные ID ролей
ACTIVITY_ROLE_IDS = [
    422500854910681089,
    1224787828815171595,
    1477953756225081394,
    831242102179758100,
    1384710674294378596,
    1267265658975031296,
    1074446816013197523,
    883270407887683615,
    
    
]

bot = discord.Bot(intents=discord.Intents.all(), debug_guilds=[GUILD_ID])
db = SqliteDatabase("TimerDataBase.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# =========================
# КЭШ КАНАЛОВ
# =========================
CHANNEL_CACHE = {"sklad": {}, "sklad_notify": {}, "simple": {}, "mpf": {}, "aktiv": {}}


# =========================
# БАЗА ДАННЫХ
# =========================
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


class Activity(BaseModel):
    priority = TextField(null=True)
    guild_id = BigIntegerField()
    channel_id = BigIntegerField()
    message_id = BigIntegerField()
    author = BigIntegerField()
    title = TextField()
    location = TextField()
    need_people = TextField()
    voice_channel_id = BigIntegerField()
    created_at = BigIntegerField()


class SkladNotification(BaseModel):
    guild_id = BigIntegerField()
    timer_message_id = BigIntegerField()
    notification_channel_id = BigIntegerField()
    notification_message_id = BigIntegerField()
    warning_key = TextField()
    created_at = BigIntegerField()


db.connect(reuse_if_open=True)
db.create_tables([ChannelConfig, Timer, Activity, SkladNotification])


def ensure_db_columns():
    # create_tables не добавляет новые колонки в уже существующие таблицы,
    # поэтому новые поля добавляются безопасно при запуске.
    with db.atomic():
        activity_columns = [col.name for col in db.get_columns(Activity._meta.table_name)]
        if "priority" not in activity_columns:
            db.execute_sql("ALTER TABLE activity ADD COLUMN priority TEXT")


ensure_db_columns()


# =========================
# КАНАЛЫ
# =========================
def load_channels():
    global CHANNEL_CACHE
    CHANNEL_CACHE = {"sklad": {}, "sklad_notify": {}, "simple": {}, "mpf": {}, "aktiv": {}}

    for row in ChannelConfig.select():
        CHANNEL_CACHE.setdefault(row.channel_type, {})
        CHANNEL_CACHE[row.channel_type][row.guild_id] = row.channel_id


def set_channel(guild_id, channel_id, channel_type):
    row = ChannelConfig.get_or_none(
        (ChannelConfig.guild_id == guild_id)
        & (ChannelConfig.channel_type == channel_type)
    )

    if row:
        row.channel_id = channel_id
        row.save()
    else:
        ChannelConfig.create(
            guild_id=guild_id,
            channel_id=channel_id,
            channel_type=channel_type,
        )

    CHANNEL_CACHE.setdefault(channel_type, {})[guild_id] = channel_id


def get_channel(guild_id, channel_type):
    return CHANNEL_CACHE.get(channel_type, {}).get(guild_id)


# =========================
# ПРАВА
# =========================
def has_access(member):
    return member.guild_permissions.administrator or any(
        role.id in ALLOWED_ROLE_IDS for role in member.roles
    )


def has_activity_access(member):
    return member.guild_permissions.administrator or any(
        role.id in ACTIVITY_ROLE_IDS for role in member.roles
    )


def can_delete_activity(member, author_id):
    return (
        member.id == author_id
        or member.guild_permissions.administrator
        or any(role.id in ALLOWED_ROLE_IDS for role in member.roles)
    )


# =========================
# ОЧИСТКА НЕСУЩЕСТВУЮЩИХ КАНАЛОВ
# =========================
def clean_channels():
    for row in ChannelConfig.select():
        guild = bot.get_guild(row.guild_id)
        if not guild or guild.get_channel_or_thread(row.channel_id) is None:
            row.delete_instance()


# =========================
# EMBED АКТИВНОСТИ
# =========================
def build_activity_embed(author, title, hex_value, region, need_people, voice_channel_id):
    now = datetime.datetime.now()
    footer_time = now.strftime("Сегодня в %H:%M")

    embed = discord.Embed(
        title=title,
        color=discord.Color.green(),
    )

    embed.add_field(name="🌐 Гекс", value=hex_value, inline=True)
    embed.add_field(name="🗺️ Регион", value=region, inline=True)
    embed.add_field(name="👥 Нужно людей", value=need_people, inline=False)
    embed.add_field(name="🔊 Голосовой канал", value=f"<#{voice_channel_id}>", inline=False)
    embed.add_field(name="👤 Создатель активности", value=author.mention, inline=False)

    if author.display_avatar:
        embed.set_thumbnail(url=author.display_avatar.url)

    embed.set_footer(text=f"Активность • {footer_time}")
    return embed



def can_delete_timer_message(member, author_id):
    return (
        member.id == author_id
        or member.guild_permissions.administrator
        or any(role.id in ALLOWED_ROLE_IDS for role in member.roles)
    )


def get_sklad_warning_key(seconds_left):
    if seconds_left <= 0:
        return None

    # Один раз примерно за 3 часа.
    if seconds_left <= 3 * 60 * 60 and seconds_left > 2 * 60 * 60:
        return "3h"

    # За последние 2 часа до последнего часа: два раза в час.
    if seconds_left <= 2 * 60 * 60 and seconds_left > 60 * 60:
        bucket = seconds_left // (30 * 60)
        return f"2h_30m_{bucket}"

    # Последний час: каждые 10 минут.
    if seconds_left <= 60 * 60:
        bucket = seconds_left // (10 * 60)
        return f"1h_10m_{bucket}"

    return None


def build_sklad_warning_text(timer_row, seconds_left):
    warning_time = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    return (
        "⚠️ **Склад скоро сгорит!**\n"
        f"{timer_row.text}\n"
        f"⏳ Осталось: <t:{timer_row.time_end}:R>\n"
        f"📍 Сообщение склада: <#{timer_row.channel_id}>\n"
        "✅ Нужно обновить склад в игре и нажать **Обновить склад** в чате складов.\n"
        f"🕒 Уведомление: <t:{warning_time}:f>"
    )


async def delete_sklad_notifications(timer_message_id):
    rows = list(SkladNotification.select().where(SkladNotification.timer_message_id == timer_message_id))
    for row in rows:
        try:
            guild = bot.get_guild(row.guild_id)
            channel = guild.get_channel_or_thread(row.notification_channel_id) if guild else None
            if channel:
                try:
                    msg = await channel.fetch_message(row.notification_message_id)
                    await msg.delete()
                except discord.NotFound:
                    pass
        except Exception:
            logger.error(traceback.format_exc())
        finally:
            row.delete_instance()


async def send_sklad_warning_if_needed(timer_row, now_ts):
    if timer_row.kind != "sklad":
        return

    notify_channel_id = get_channel(timer_row.guild_id, "sklad_notify")
    if not notify_channel_id:
        return

    seconds_left = timer_row.time_end - now_ts
    warning_key = get_sklad_warning_key(seconds_left)
    if not warning_key:
        return

    exists = SkladNotification.get_or_none(
        (SkladNotification.timer_message_id == timer_row.message_id)
        & (SkladNotification.warning_key == warning_key)
    )
    if exists:
        return

    guild = bot.get_guild(timer_row.guild_id)
    channel = guild.get_channel_or_thread(notify_channel_id) if guild else None
    if not channel:
        return

    msg = await channel.send(build_sklad_warning_text(timer_row, seconds_left))
    SkladNotification.create(
        guild_id=timer_row.guild_id,
        timer_message_id=timer_row.message_id,
        notification_channel_id=notify_channel_id,
        notification_message_id=msg.id,
        warning_key=warning_key,
        created_at=now_ts,
    )

# =========================
# КНОПКИ
# =========================

class PriorityView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(PriorityButton("🔴", "high", discord.Color.from_rgb(255, 0, 0)))
        self.add_item(PriorityButton("🟠", "medium", discord.Color.orange()))
        self.add_item(PriorityButton("🟡", "low", discord.Color.gold()))
        self.add_item(PriorityButton("🟢", "minimal", discord.Color.green()))

class PriorityButton(Button):
    def __init__(self, emoji, value, color):
        super().__init__(emoji=emoji, style=discord.ButtonStyle.secondary, custom_id=f"priority_{value}")
        self.value = value
        self.embed_color = color

    async def callback(self, interaction: discord.Interaction):
        row = Activity.get_or_none(Activity.message_id == interaction.message.id)
        if not row:
            return await interaction.response.send_message("❌ Не найдено", ephemeral=True)

        if interaction.user.id != row.author:
            return await interaction.response.send_message("❌ Только автор", ephemeral=True)

        row.priority = self.value
        row.save()

        embed = interaction.message.embeds[0]
        embed.color = self.embed_color

        priority_text = {
            "high": "🔴 Высокий",
            "medium": "🟠 Средний",
            "low": "🟡 Низкий",
            "minimal": "🟢 Минимальный",
        }

        embed.add_field(name="⚡ Приоритет", value=priority_text[self.value], inline=False)

        await interaction.response.edit_message(embed=embed, view=ActivityView())

class SkladView(View):
    def __init__(self):
        super().__init__(timeout=None)

        btn_update = Button(
            label="Обновить склад",
            style=discord.ButtonStyle.green,
            custom_id="sklad_update",
        )
        btn_delete = Button(
            label="Удалить",
            style=discord.ButtonStyle.red,
            custom_id="sklad_delete",
        )

        btn_update.callback = self.update
        btn_delete.callback = self.delete

        self.add_item(btn_delete)
        self.add_item(btn_update)

    async def update(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row:
            return await interaction.followup.send("❌ Не найдено", ephemeral=True)

        now = datetime.datetime.now(datetime.timezone.utc)
        new_end = int((now + datetime.timedelta(hours=48)).timestamp())

        row.time_end = new_end
        row.save()
        await delete_sklad_notifications(row.message_id)

        member = interaction.guild.get_member(interaction.user.id)
        nickname = member.display_name if member else "пользователь"

        updated_text = (
            f"{row.text}\n"
            f"⏰ До окончания: <t:{new_end}:R>\n"
            f"🔄 Обновил склад - {nickname}"
        )

        await interaction.message.edit(content=updated_text, view=self)

    async def delete(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row:
            return await interaction.followup.send("❌ Не найдено", ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not member or not can_delete_timer_message(member, row.author):
            return await interaction.followup.send("❌ Нет прав на удаление", ephemeral=True)

        await delete_sklad_notifications(row.message_id)
        row.delete_instance()
        await interaction.message.delete()


class SkladExpiredView(View):
    def __init__(self):
        super().__init__(timeout=None)

        btn_delete = Button(
            label="Удалить",
            style=discord.ButtonStyle.red,
            custom_id="sklad_expired_delete",
        )
        btn_delete.callback = self.delete
        self.add_item(btn_delete)

    async def delete(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row:
            return await interaction.followup.send("❌ Не найдено", ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not member or not can_delete_timer_message(member, row.author):
            return await interaction.followup.send("❌ Нет прав на удаление", ephemeral=True)

        await delete_sklad_notifications(row.message_id)
        row.delete_instance()
        await interaction.message.delete()


class TimerView(View):
    def __init__(self):
        super().__init__(timeout=None)

        btn = Button(
            label="Удалить таймер",
            style=discord.ButtonStyle.red,
            custom_id="timer_delete",
        )
        btn.callback = self.delete
        self.add_item(btn)

    async def delete(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return await interaction.followup.send("❌ Только автор", ephemeral=True)

        row.delete_instance()
        await interaction.message.delete()


class MPFView(View):
    def __init__(self, show_take=False):
        super().__init__(timeout=None)

        delete = Button(
            label="Удалить таймер",
            style=discord.ButtonStyle.red,
            custom_id="mpf_delete",
        )
        delete.callback = self.delete
        self.add_item(delete)

        take = Button(
            label="Забрал заказ",
            style=discord.ButtonStyle.green,
            custom_id="mpf_take",
            disabled=not show_take,
        )
        take.callback = self.take
        self.add_item(take)

    async def take(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or row.taken_by:
            return await interaction.followup.send("❌ Уже забрали", ephemeral=True)

        row.taken_by = interaction.user.id
        row.save()

        member = interaction.guild.get_member(interaction.user.id)
        nickname = member.display_name if member else "пользователь"

        await interaction.message.edit(
            content=interaction.message.content + f"\n\n📦 Забрал: {nickname}",
            view=MPFView(show_take=False),
        )
        await interaction.followup.send("✅ Забрал", ephemeral=True)

    async def delete(self, interaction):
        await interaction.response.defer()

        row = Timer.get_or_none(Timer.message_id == interaction.message.id)
        if not row or interaction.user.id != row.author:
            return await interaction.followup.send("❌ Только автор", ephemeral=True)

        row.delete_instance()
        await interaction.message.delete()


class ActivityView(View):
    def __init__(self):
        super().__init__(timeout=None)

        delete = Button(
            label="Удалить активность",
            style=discord.ButtonStyle.red,
            custom_id="activity_delete",
        )
        delete.callback = self.delete
        self.add_item(delete)

    async def delete(self, interaction):
        await interaction.response.defer()

        row = Activity.get_or_none(Activity.message_id == interaction.message.id)
        if not row:
            return await interaction.followup.send("❌ Активность не найдена", ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not member or not can_delete_activity(member, row.author):
            return await interaction.followup.send(
                "❌ Удалить активность может только создатель, администратор или спец.роль",
                ephemeral=True,
            )

        row.delete_instance()
        await interaction.message.delete()


# =========================
# ЦИКЛ ТАЙМЕРОВ
# =========================
@tasks.loop(seconds=30)
async def loop():
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    for t in Timer.select().where((Timer.time_end >= now) & (Timer.kind == "sklad")):
        try:
            await send_sklad_warning_if_needed(t, now)
        except Exception:
            logger.error(traceback.format_exc())

    expired = Timer.select().where(
        (Timer.time_end < now)
        & (Timer.kind.in_(["mpf", "timer", "sklad"]))
    )

    for t in expired:
        try:
            guild = bot.get_guild(t.guild_id)
            if not guild:
                t.delete_instance()
                continue

            channel = guild.get_channel_or_thread(t.channel_id)
            if not channel:
                t.delete_instance()
                continue

            try:
                msg = await channel.fetch_message(t.message_id)
            except discord.NotFound:
                t.delete_instance()
                continue

            member = guild.get_member(t.author)
            nickname = member.display_name if member else "пользователь"
            mention = member.mention if member else "пользователь"

            if t.kind == "mpf":
                item = t.text
                marker = "📦 Что поставил: "
                if marker in item:
                    item = item.split(marker, 1)[1].splitlines()[0]

                await msg.edit(
                    content=(
                        f"👤 Кто поставил: {nickname}\n"
                        f"📦 Что поставил: {item}\n"
                        f"📦 Ящиков: {t.boxes}\n"
                        f"✅ Статус: готово"
                    ),
                    view=MPFView(show_take=True),
                )

                t.kind = "mpf_ready"
                t.save()
                continue

            if t.kind == "timer":
                await msg.edit(
                    content=(
                        f"👤 {mention}\n"
                        f"📌 {t.text}\n"
                        f"✅ Статус: готово"
                    ),
                    view=TimerView(),
                )

                t.kind = "timer_done"
                t.save()
                continue

            if t.kind == "sklad":
                await delete_sklad_notifications(t.message_id)
                await msg.edit(
                    content=(
                        f"🔥 **Склад сгорел**\n"
                        f"{t.text}\n"
                        f"⏰ Сгорел: <t:{now}:f> (<t:{now}:R>)"
                    ),
                    view=SkladExpiredView(),
                )
                t.kind = "sklad_done"
                t.save()

        except Exception:
            logger.error(traceback.format_exc())
            t.delete_instance()


# =========================
# ЗАПУСК БОТА
# =========================
@bot.event
async def on_ready():
    logger.info(f"Бот онлайн: {bot.user}")

    clean_channels()
    load_channels()

    bot.add_view(SkladView())
    bot.add_view(SkladExpiredView())
    bot.add_view(TimerView())
    bot.add_view(MPFView())
    bot.add_view(ActivityView())
    bot.add_view(PriorityView())

    if not loop.is_running():
        loop.start()


# =========================
# КОМАНДЫ НАСТРОЙКИ
# =========================
@bot.slash_command(name="setskladchat", guild_ids=[GUILD_ID])
async def установить_чат_склада(
    ctx,
    канал_склада: discord.TextChannel = None,
    канал_уведомлений: discord.TextChannel = None,
    айди_ветки: str = None,
):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    target_id = None

    if канал_склада:
        target_id = канал_склада.id
    elif айди_ветки:
        try:
            target_id = int(айди_ветки)
        except ValueError:
            return await ctx.respond("❌ Неверный ID ветки", ephemeral=True)
    else:
        return await ctx.respond("❌ Укажи канал_склада или айди_ветки", ephemeral=True)

    if not канал_уведомлений:
        return await ctx.respond("❌ Укажи канал_уведомлений", ephemeral=True)

    set_channel(ctx.guild.id, target_id, "sklad")
    set_channel(ctx.guild.id, канал_уведомлений.id, "sklad_notify")

    await ctx.respond(
        f"✅ Чат склада установлен: {target_id}\n"
        f"🔔 Чат уведомлений склада установлен: {канал_уведомлений.mention}",
        ephemeral=True,
    )


@bot.slash_command(name="setsimpletimer", guild_ids=[GUILD_ID])
async def установить_чат_таймера(
    ctx,
    канал: discord.TextChannel = None,
    айди_ветки: str = None,
):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    target_id = None

    if канал:
        target_id = канал.id
    elif айди_ветки:
        try:
            target_id = int(айди_ветки)
        except ValueError:
            return await ctx.respond("❌ Неверный ID ветки", ephemeral=True)
    else:
        return await ctx.respond("❌ Укажи канал или айди_ветки", ephemeral=True)

    set_channel(ctx.guild.id, target_id, "simple")
    await ctx.respond(f"✅ Чат таймера установлен: {target_id}", ephemeral=True)


@bot.slash_command(name="setmpfchat", guild_ids=[GUILD_ID])
async def установить_чат_мпф(
    ctx,
    канал: discord.TextChannel = None,
    айди_ветки: str = None,
):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    target_id = None

    if канал:
        target_id = канал.id
    elif айди_ветки:
        try:
            target_id = int(айди_ветки)
        except ValueError:
            return await ctx.respond("❌ Неверный ID ветки", ephemeral=True)
    else:
        return await ctx.respond("❌ Укажи канал или айди_ветки", ephemeral=True)

    set_channel(ctx.guild.id, target_id, "mpf")
    await ctx.respond(f"✅ Чат МПФ установлен: {target_id}", ephemeral=True)


@bot.slash_command(name="setactivitychat", guild_ids=[GUILD_ID])
async def установить_чат_активностей(
    ctx,
    канал: discord.TextChannel = None,
    айди_ветки: str = None,
):
    if not has_access(ctx.author):
        return await ctx.respond("❌ Нет прав", ephemeral=True)

    target_id = None

    if канал:
        target_id = канал.id
    elif айди_ветки:
        try:
            target_id = int(айди_ветки)
        except ValueError:
            return await ctx.respond("❌ Неверный ID ветки", ephemeral=True)
    else:
        return await ctx.respond("❌ Укажи канал или айди_ветки", ephemeral=True)

    set_channel(ctx.guild.id, target_id, "aktiv")
    await ctx.respond(f"✅ Чат активностей установлен: {target_id}", ephemeral=True)


# =========================
# КОМАНДА: ТАЙМЕР
# =========================
@bot.slash_command(name="таймер", guild_ids=[GUILD_ID])
async def таймер(
    ctx,
    название: str,
    дни: int = 0,
    часы: int = 0,
    минуты: int = 0,
):
    if дни == 0 and часы == 0 and минуты == 0:
        return await ctx.respond("❌ Укажи время", ephemeral=True)

    channel_id = get_channel(ctx.guild.id, "simple")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ Не тот канал", ephemeral=True)

    await ctx.defer(ephemeral=True)

    end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=дни,
        hours=часы,
        minutes=минуты,
    )
    end_ts = int(end.timestamp())

    msg = await ctx.send(
        f"👤 {ctx.author.mention}\n📌 {название}\n⏰ <t:{end_ts}:R>",
        view=TimerView(),
    )

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=название,
        time_end=end_ts,
        author=ctx.author.id,
        kind="timer",
    )

    await ctx.followup.send("✅ Таймер создан", ephemeral=True)


# =========================
# КОМАНДА: СКЛАД
# =========================
@bot.slash_command(name="склад", guild_ids=[GUILD_ID])
async def склад(ctx, гекс: str, регион: str, склад: str, пароль: str):
    channel_id = get_channel(ctx.guild.id, "sklad")
    if channel_id and ctx.channel.id != channel_id:
        return await ctx.respond("❌ Не тот канал", ephemeral=True)

    await ctx.defer(ephemeral=True)

    end_ts = int(
        (
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=48)
        ).timestamp()
    )

    text = (
        f"👤 {ctx.author.display_name}\n"
        f"**Гекс:** {гекс}\n"
        f"**Регион:** {регион}\n"
        f"**Склад:** {склад}\n"
        f"**Пароль:** {пароль}"
    )

    msg = await ctx.send(
        f"{text}\n⏰ До окончания: <t:{end_ts}:R>",
        view=SkladView(),
    )

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=text,
        time_end=end_ts,
        author=ctx.author.id,
        kind="sklad",
    )

    await ctx.followup.send("✅ Склад создан", ephemeral=True)


# =========================
# КОМАНДА: МПФ
# =========================
@bot.slash_command(name="мпф", guild_ids=[GUILD_ID])
async def мпф(
    ctx,
    что_поставил: str,
    ящиков: int,
    дни: int = 0,
    часы: int = 0,
    минуты: int = 0,
):
    if дни == 0 and часы == 0 and минуты == 0:
        return await ctx.respond("❌ Укажи время", ephemeral=True)

    channel_id = get_channel(ctx.guild.id, "mpf")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ Не тот канал", ephemeral=True)

    await ctx.defer(ephemeral=True)

    end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=дни,
        hours=часы,
        minutes=минуты,
    )
    end_ts = int(end.timestamp())

    text = (
        f"👤 Кто поставил: {ctx.author.display_name}\n"
        f"📦 Что поставил: {что_поставил}\n"
        f"📦 Ящиков: {ящиков}\n"
        f"⌛ <t:{end_ts}:R>\n"
        f"Статус: ожидание"
    )

    msg = await ctx.send(text, view=MPFView(show_take=False))

    Timer.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        text=text,
        time_end=end_ts,
        author=ctx.author.id,
        kind="mpf",
        boxes=ящиков,
        taken_by=None,
    )

    await ctx.followup.send("✅ МПФ создан", ephemeral=True)


# =========================
# КОМАНДА: АКТИВНОСТЬ
# =========================
@bot.slash_command(name="активность", guild_ids=[GUILD_ID])
async def активность(
    ctx,
    название_активности: str,
    гекс: str,
    регион: str,
    нужно_людей: str,
    голосовой_канал: discord.VoiceChannel,
):
    if not has_activity_access(ctx.author):
        return await ctx.respond("❌ Нет прав на создание активности", ephemeral=True)

    channel_id = get_channel(ctx.guild.id, "aktiv")
    if not channel_id or ctx.channel.id != channel_id:
        return await ctx.respond("❌ Не тот канал", ephemeral=True)

    await ctx.defer(ephemeral=True)

    created_at = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    embed = build_activity_embed(
        author=ctx.author,
        title=название_активности,
        hex_value=гекс,
        region=регион,
        need_people=нужно_людей,
        voice_channel_id=голосовой_канал.id,
    )

    msg = await ctx.send(embed=embed, view=PriorityView())

    Activity.create(
        guild_id=ctx.guild.id,
        channel_id=ctx.channel.id,
        message_id=msg.id,
        author=ctx.author.id,
        title=название_активности,
        location=f"Гекс: {гекс}\nРегион: {регион}",
        need_people=нужно_людей,
        voice_channel_id=голосовой_канал.id,
        created_at=created_at,
    )

    await ctx.followup.send("✅ Активность создана", ephemeral=True)


# =========================
# RUN
# =========================
token = os.environ.get("DISCORD_BOT_TOKEN")
if not token:
    raise RuntimeError("Не найден DISCORD_BOT_TOKEN. Добавь токен в переменные окружения/Secrets, а не в .txt файл.")

bot.run(token)
