# -*- coding: utf-8 -*-

from typing import Optional, Callable, Awaitable, Tuple, Union, List, TypeVar

from discord import Member, Embed

from commands.base.client import Ratelimit
from . import bot, Command, CommandError, authorise, Context
from . import get_alias, toggle_alias
from . import language
from . import toggle_botban, get_guild_botbans
from . import toggle, is_toggled, get_guild_toggles, CommandToggle
from . import Lister, BasePager
from . import database
from .authority import bot_mod, bot_admin, pm, no_pm, owner
from .converters import Required


# =====================
# === Alias Command ===
# =====================

@authorise(no_pm)
@bot.command()
async def alias(ctx, *, new_alias=None):
    if new_alias is None:
        aliases = (await get_alias(ctx.guild_id)).copy()
        # this uses the fact that the ping invokers will
        # always be at the start of the list, unless the main
        # invoker is present somewhere
        if bot.invoker in aliases:
            aliases.remove(bot.invoker)
            aliases = [f"<@{bot.user.id}>", bot.invoker] + aliases[2:]
        else:
            aliases = [f"<@{bot.user.id}>"] + aliases[2:]
        await ctx.post_line("alias_list", str(aliases)[1:-1])
    else:
        if "@" in new_alias:
            raise CommandError("no_pings")
        new_alias = new_alias.strip()
        added = await toggle_alias(ctx.guild_id, new_alias)
        if added:
            await ctx.post_line("add_alias", new_alias)
        else:
            await ctx.post_line("remove_alias", new_alias)


# ========================
# === Language Command ===
# ========================

async def language_auth(ctx):
    return (await pm(ctx)) or (await bot_admin(ctx))


@authorise(language_auth, "bot_admin")
@bot.command("language")
async def language_command(ctx, newlang=None, set_guild=None):
    if newlang is None:
        line = ctx.get_raw_output("lang_list_entry")
        lang_entries = "\n".join(
            line.format(name=name, id=lang)
            for lang, name in language.get_language_names().items()
            if not lang.startswith("testing")
        )
        await ctx.post_line("lang_list", lang_entries)
        return

    newlang = newlang.lower()
    if newlang not in language.LanguageManager.data:
        raise CommandError("invalid_lang")

    if set_guild in ["server", "guild"] and not ctx.is_private:
        await language.set_guild_lang(ctx.guild_id, newlang)
        ctx._lang = newlang
        await ctx.post_line("success_guild")
    else:
        await language.set_channel_lang(ctx.channel_id, newlang)
        ctx._lang = newlang
        await ctx.post_line("success_channel")


# ======================
# === Botban Command ===
# ======================

async def list_botbans(ctx: Context):
    users = []
    for uid in await get_guild_botbans(ctx.guild_id):
        user = ctx.guild.get_member(uid)
        if user:
            users.append(user.name)

    if not users:
        raise CommandError("no_botbanned_users")

    await Lister(ctx, *users).start()


@authorise(no_pm)
@authorise(bot_mod)
@bot.command("botban")
async def botban_command(ctx: Context, target: Optional[Member] = None):
    if target is None:
        return await list_botbans(ctx)
    # Cannot botban guild owner, guild admin, or bot coowner
    if ctx.guild.owner_id == target.id:
        raise CommandError("target_owner")
    if target.id in ctx.bot.coowners:
        raise CommandError("target_bot_owner")
    if target.guild_permissions.administrator:
        raise CommandError("target_admin")

    is_botbanned = await toggle_botban(target.id, ctx.guild_id)
    message = "success_ban" if is_botbanned else "success_unban"

    await ctx.post_line(message)


# ====================
# === Help Command ===
# ====================

# Define some decorators inside a Help "module" to make importing cleaner
class Help:
    _interjections = []
    _failures = []

    @classmethod
    def command_help_interjections(cls, func: Callable[[Command, Context,
                                                        Embed], None]):
        cls._interjections.append(func)
        return func

    @classmethod
    def run_interjections(cls, cmd: Command, ctx: Context, embed: Embed):
        for func in cls._interjections:
            func(cmd, ctx, embed)

    @classmethod
    def on_command_help_fail(cls, func: Callable[[Context, Tuple[str, ...]],
                                                 Awaitable[bool]]):
        cls._failures.append(func)
        return func

    @classmethod
    async def run_external_help(cls, ctx: Context, path: Tuple[str, ...]):
        for func in cls._failures:
            if await func(ctx, path):
                return


def ratelimit_to_line(invocations: int, time: int, ctx: Context) -> str:
    if time > 180 or time % 60 == 0:
        period = ctx.get_output("rl_minutes", time//60, numerical_ref=time//60)
    else:
        period = ctx.get_output("rl_seconds", time, numerical_ref=time)

    calls = ctx.get_output("rl_invocations", invocations,
                           numerical_ref=invocations)

    return f"{calls} {period}"


async def add_permissions(target: Command, ctx: Context, embed: Embed) -> None:
    perms = []
    for auth, name in target.auth.items():
        if isinstance(auth, Ratelimit):
            # Handle ratelimits separate
            line = ratelimit_to_line(auth.invocations, auth.cooldown, ctx)
            header = ctx.get_output("rl_header")
            embed.add_field(name=header, value=line)

        elif isinstance(auth, CommandToggle) and \
                (await is_toggled(ctx.guild_id, target.qualified_id)):

            # Handle toggles separate
            header = ctx.get_output("toggle_header")
            body = ctx.get_output("toggle_body")
            embed.add_field(name=header, value=body)

        elif name in ["toggle", "bot_banned"]:
            # Do not show toggle or bot_banned on root
            pass

        else:
            perms.append(name.replace("_", " ") \
                             .title() \
                             .replace("Pm", "PM"))  # Special case for "No PM"

    if perms:
        line = ", ".join(perms)
        header = ctx.get_output("auth_header")
        embed.add_field(name=header, value=line)

    Help.run_interjections(target, ctx, embed)


@bot.command("help")
async def help_command(ctx: Context, *path: str):
    # Allow access to root since we are inside the framework anyway.
    target: Command = ctx.bot.root_command

    # Get the command or subcommand we want to access.

    successes = []
    for element in path:
        found = target.subcommands.get(f"{ctx.lang}_{element}",
                                       target.subcommands.get(element))
        if found is None:
            if target.parent is None:
                return await Help.run_external_help(ctx, path)
            else:
                raise CommandError("command_not_found",
                                   ctx.invoker + " ".join(successes))

        successes.append(element)
        target = found

    # Build the messages. Page 1 will have a description and usage
    # Pages 2 onwards will have different subcommands.

    # Get all the relevant information first.
    if not path:
        name = language.get_output(ctx.command, "bot_help_title", ctx)
    else:
        name = ctx.invoker + " ".join(path)
    uri = language.get_command_link(target, ctx)
    desc = language.get_command_description(target, ctx)

    usages = language.get_command_help_lines(target, ctx)
    subcommands = []

    for sub in set(target.subcommands.values()):
        if await sub.validate_auth(ctx) is None:
            try:
                line = language.get_command_parent_help(sub, ctx)
                subcommands.append(line)
            except language.LanguageError:
                pass

    pages = []

    # Set up first page
    header = ctx.get_output("link_header")
    embed = Embed(description=desc)
    embed.set_author(name=f"{name} | {header}", url=uri)

    await add_permissions(target, ctx, embed)

    pages.append(embed)

    if usages:
        header = ctx.get_output("usage_header")
        embed = Embed()
        embed.set_author(name=f"{name} | {header}", url=uri)

        for title, value in usages:
            embed.add_field(name=title, value=value, inline=False)

        pages.append(embed)

    # Chunk up subcommands
    chunks = [subcommands[i:i+6] for i in range(0, len(subcommands), 6)]

    header = ctx.get_output("subcommand_header")

    for chunk in chunks:
        embed = Embed()
        embed.set_author(name=f"{name} | {header}", url=uri)

        for line in chunk:
            embed.add_field(name=line[0], value=line[1], inline=False)

        pages.append(embed)

    await BasePager(ctx, *pages).start()


# ======================
# === Toggle Command ===
# ======================

T = TypeVar("T")

@bot.converter()
def toggle_path(arg: str, ctx: Context) -> Union[Command, List[Command]]:
    target = ctx.bot.root_command
    path = arg.split(".")

    while path:
        element = path.pop(0)

        if element == "*":
            return list(set(target.subcommands.values()))

        target = target.subcommands.get(f"{ctx.lang}_{element}",
                                        target.subcommands.get(element))

        if target is None:
            raise CommandError("TOGGLE_PATH_error", path)

    return target


def flatten(*elements: Union[T, List[T], Tuple[T]]) -> List[T]:
    output = []
    for element in elements:
        if isinstance(element, (list, tuple)):
            output.extend(element)
        else:
            output.append(element)

    return output


async def toggle_shared_function(ctx: Context, *commands: Command):
    prefix = ctx.command.id
    # Throw if prefix is not one of "enable", "disable" or "toggle"
    updater = getattr(toggle, f"{prefix}_elements")

    paths = [cmd.qualified_id for cmd in commands]

    await updater(ctx.guild_id, *paths)

    await ctx.post_line("success", ", ".join(paths), numerical_ref=len(commands))


@authorise(bot_admin)
@bot.command("toggle")
async def toggle_command(ctx: Context, *commands: Required[toggle_path]):
    await toggle_shared_function(ctx, *flatten(*commands))


@toggle_command.subcommand("disable")
async def toggle_disable(ctx: Context, *commands: Required[toggle_path]):
    await toggle_shared_function(ctx, *flatten(*commands))


@toggle_command.subcommand("enable")
async def toggle_enable(ctx: Context, *commands: Required[toggle_path]):
    await toggle_shared_function(ctx, *flatten(*commands))


@toggle_command.subcommand("list")
async def toggle_list(ctx: Context):
    toggles = sorted(await get_guild_toggles(ctx.guild_id))
    if len(toggles) == 0:
        raise CommandError("no_toggles")
    await ctx.post_line("toggle_list", ", ".join(toggles))


# ====================
# === Quit Command ===
# ====================

@authorise(owner)
@bot.command("quit")
async def quit_command(ctx: Context):
    await bot._bot.logout()
