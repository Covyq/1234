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
    1493199914572972032,
    1477953756225081394,
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
CHANNEL_CACHE = {"sklad": {}, "simple": {}, "mpf": {}, "aktiv": {}}


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
    guild_id = BigIntegerField()
    channel_id = BigIntegerField()
    message_id = BigIntegerField()
    author = BigIntegerField()
    title = TextField()
    location = TextField()
    need_people = TextField()
    voice_channel_id = BigIntegerField()
    created_at = BigIntegerField()


db.connect(reuse_if_open=True)
db.create_tables([ChannelConfig, Timer, Activity])


# =========================
# КАНАЛЫ
# =========================
def load_channels():
    global CHANNEL_CACHE
    CHANNEL_CACHE = {"sklad": {}, "simple": {}, "mpf": {}, "aktiv": {}}

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

# =========================
# КНОПКИ
# =========================
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
        if not row or interaction.user.id != row.author:
            return await interaction.followup.send("❌ Только автор", ephemeral=True)

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
            view=self,
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
    PRIORITIES = {
        "activity_priority_red": {
            "label": "🔴 Красный",
            "style": discord.ButtonStyle.red,
            "color": discord.Color.red(),
            "name": "Красный",
        },
        "activity_priority_orange": {
            "label": "🟠 Оранжевый",
            "style": discord.ButtonStyle.primary,
            "color": discord.Color.orange(),
            "name": "Оранжевый",
        },
        "activity_priority_yellow": {
            "label": "🟡 Жёлтый",
            "style": discord.ButtonStyle.secondary,
            "color": discord.Color.gold(),
            "name": "Жёлтый",
        },
        "activity_priority_green": {
            "label": "🟢 Зелёный",
            "style": discord.ButtonStyle.green,
            "color": discord.Color.green(),
            "name": "Зелёный",
        },
    }

    def __init__(self, show_priority=True):
        super().__init__(timeout=None)

        if show_priority:
            for custom_id, data in self.PRIORITIES.items():
                priority_button = Button(
                    label=data["label"],
                    style=data["style"],
                    custom_id=custom_id,
                )
                priority_button.callback = self.priority
                self.add_item(priority_button)

        delete = Button(
            label="Удалить активность",
            style=discord.ButtonStyle.red,
            custom_id="activity_delete",
        )
        delete.callback = self.delete
        self.add_item(delete)

    async def priority(self, interaction):
        await interaction.response.defer(ephemeral=True)

        row = Activity.get_or_none(Activity.message_id == interaction.message.id)
        if not row:
            return await interaction.followup.send("❌ Активность не найдена", ephemeral=True)

        if interaction.user.id != row.author:
            return await interaction.followup.send(
                "❌ Приоритет может выбрать только создатель активности",
                ephemeral=True,
            )

        priority = self.PRIORITIES.get(interaction.data.get("custom_id"))
        if not priority:
            return await interaction.followup.send("❌ Неизвестный приоритет", ephemeral=True)

        if not interaction.message.embeds:
            return await interaction.followup.send("❌ Embed активности не найден", ephemeral=True)

        embed = discord.Embed.from_dict(interaction.message.embeds[0].to_dict())
        embed.color = priority["color"]

        await interaction.message.edit(
            embed=embed,
            view=ActivityView(show_priority=False),
        )

        await interaction.followup.send(
            f"✅ Приоритет установлен: {priority['name']}",
            ephemeral=True,
        )

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
    expired = Timer.select().where(Timer.time_end < now)

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
                item = t.text.split("📦 Что поставил: ")[1].splitlines()[0]

                await msg.edit(
                    content=(
                        f"👤 Кто поставил: {nickname}\n"
                        f"📦 Что поставил: {item}\n"
                        f"📦 Ящиков: {t.boxes}\n"
                        f"Статус: ✅"
                    ),
                    view=MPFView(show_take=True),
                )

                t.time_end = now + 10**9
                t.save()
                continue

            if t.kind == "timer":
                await msg.edit(
                    content=(
                        f"👤 {mention}\n"
                        f"📌 {t.text}\n"
                        f"✅ Статус: выполнено"
                    ),
                    view=TimerView(),
                )

                t.time_end = now + 10**9
                t.save()
                continue

            if t.kind == "sklad":
                await msg.edit(
                    content=f"✅ Склад завершён {nickname}\n⏰ <t:{now}:R>",
                    view=None,
                )
                t.delete_instance()

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
    bot.add_view(TimerView())
    bot.add_view(MPFView())
    bot.add_view(ActivityView())

    if not loop.is_running():
        loop.start()


# =========================
# КОМАНДЫ НАСТРОЙКИ
# =========================
@bot.slash_command(name="установить_чат_склада", guild_ids=[GUILD_ID])
async def установить_чат_склада(
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

    set_channel(ctx.guild.id, target_id, "sklad")
    await ctx.respond(f"✅ Чат склада установлен: {target_id}", ephemeral=True)


@bot.slash_command(name="установить_чат_таймера", guild_ids=[GUILD_ID])
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


@bot.slash_command(name="установить_чат_мпф", guild_ids=[GUILD_ID])
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


@bot.slash_command(name="установить_чат_активностей", guild_ids=[GUILD_ID])
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

    msg = await ctx.send(embed=embed, view=ActivityView())

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
