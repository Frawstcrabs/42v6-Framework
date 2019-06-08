# -*- coding: utf-8 -*-

from . import bot, Context, is_botbanned
import discord
import re


async def default(ctx: Context):
    """Base auth message that always returns True."""
    return True


async def owner(ctx: Context):
    """Auth function to only allow the owner/cooowners of this bot."""
    return ctx.author.id in [bot.owner, *bot.coowners]


async def buds(ctx):
    """Auth function to only allow users in the friends list in the bot config"""
    return str(ctx.author.id) in bot.config["friends"]


async def _patrons(member):
    guild = bot.get_guild(149866687615729665)
    if guild is None:
        return False
    member = guild.get_member(member.id)
    if member is None:
        return False

    return 382900868195942401 in [r.id for r in member.roles]


def _patron_features(member):
    if isinstance(member, int):
        member = discord.Object(member)
    return (member.id in [bot.owner, *bot.coowners]
            or str(member.id) in bot.config["friends"]
            or _patrons(member))


async def patrons(ctx: Context):
    """Auth function to only allow users that are patrons of 42's patreon"""
    return _patron_features(ctx.author)


async def pm(ctx: Context):
    """Auth function to ensure the command is invoked in a DM"""
    return ctx.is_private


async def no_pm(ctx: Context):
    """Auth function to ensure the command is invoked outside of a DM"""
    return not ctx.is_private


async def guild_owner(ctx: Context):
    """
    Auth function to only allow the owner of the guild the command is being
    invoked in
    """
    if await pm(ctx):
        return False
    return ctx.guild.owner.id == ctx.author.id


# server admins no longer explicitly have all other permissions
async def guild_admin(ctx: Context):
    """Auth function to allow users with the Manage Roles permission."""
    if await pm(ctx):
        return False
    if await guild_owner(ctx):
        return True
    return ctx.author.guild_permissions.manage_roles


async def guild_manager(ctx: Context):
    """Auth function to allow users with the Manage Channels permission."""
    if await pm(ctx):
        return False
    if await guild_owner(ctx):
        return True
    return ctx.author.guild_permissions.manage_channels


async def channel_manager(ctx: Context):
    if await pm(ctx):
        return False
    if await guild_owner(ctx):
        return True
    return ctx.author.permissions_in(ctx.channel)


async def bot_admin(ctx: Context):
    if await pm(ctx):
        return False
    if await guild_admin(ctx):
        return True
#   if ctx.guild.id in powermods:
#       if ctx.author.id in powermods[ctx.guild.id]:
#           return True
    role = discord.utils.find(
        lambda r: re.match("((best *friends?)|(bot *admins?))", r.name.lower(),
                           re.I) is not None,
        ctx.author.roles
    )
    return role is not None


async def guild_mod(ctx: Context):
    """
    Auth function to allow users with the Manage Messages permission for all
    channels.
    """
    if await pm(ctx):
        return False
    if await guild_owner(ctx):
        return True
    return ctx.author.guild_permissions.manage_messages


async def channel_mod(ctx: Context):
    """
    Auth function to allow users with the Manage Messages permission in the
    channel the command is being invoked in.
    """
    if await pm(ctx):
        return False
    if await guild_owner(ctx):
        return True
    return ctx.author.permissions_in(ctx.channel).manage_messages


async def bot_mod(ctx: Context):
    """
    Auth function to allow either guild mods, guild admins or users with a role
    named some variation of "best friend" or "bot mod".
    """
    if await pm(ctx):
        return False
    if (await guild_mod(ctx)) or (await guild_admin(ctx)):
        return True
    role = discord.utils.find(
        lambda r: re.match("(((best *)?friends?)|(bot *mod(erator)?s?))",
                           r.name.lower(), re.I) is not None,
        ctx.author.roles
    )
    return role is not None


#  Currently not used
async def shitposter(ctx: Context):
    """
    Auth function to allow bot mods with a role named some variation of
    shitposting machine.
    """
    if not await bot_mod(ctx):
        return False
    role = discord.utils.find(
        lambda r: re.compile("shitpost(er|ing)? ?(machine)?").match(r.name.lower()) is not None,
        ctx.guild.me.roles
    )
    return role is not None


async def bot_banned(ctx: Context):
    """Auth function that checks if a user is botbanned in the guild."""
    if isinstance(ctx.author, discord.User):
        return False
    if await guild_owner(ctx):
        return False
    if ctx.author.permissions_in(ctx.channel).administrator:
        return False
    return is_botbanned(ctx.author_id, ctx.guild_id)
