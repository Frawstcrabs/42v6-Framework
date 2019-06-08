# -*- coding: utf-8 -*-

from __future__ import annotations

import cachetools
from typing import List, Optional

from . import db
from .client import bot


# Internal cache of botbanned users, to reduce unnecessary database queries
_botban_cache = cachetools.LFUCache(100)


async def is_botbanned(user_id: int, guild_id: Optional[int]) -> bool:
    """
    Return if this user is botbanned in this guild.

    :param user_id: ID of user
    :param guild_id: ID of guild
    :return: boolean of whether the user is botbanned
    """
    if guild_id is None:
        return False

    return user_id in await get_guild_botbans(guild_id)


async def get_user_botbans(user_id: int) -> List[int]:
    """
    Retrieve a list of all guilds this user is botbanned in.

    :param user_id: User ID to search for
    :return: List of guild IDs that have botbanned this user
    """
    ret = await db.fetchall("""
        SELECT guild_id FROM botbans
        WHERE user_id = %s
    """, user_id)

    return [row[0] for row in ret]


async def get_guild_botbans(guild_id: int) -> List[int]:
    """
    Retrieve a list of all users botbanned in this guild.

    :param guild_id: ID of guild to search in
    :return: List of IDs of all botbanned users in this guild
    """
    try:
        return _botban_cache[guild_id]
    except KeyError:
        ret = await db.fetchall("""
            SELECT user_id FROM botbans
            WHERE guild_id = %s 
        """, guild_id)

        ret = [row[0] for row in ret]

        _botban_cache[guild_id] = ret

        return ret


async def toggle_botban(user_id: int, guild_id: int) -> bool:
    """
    Toggle whether a user is botbanned in a guild.

    :param user_id: ID of user to toggle botban for
    :param guild_id: ID of guild toggle botban in
    :return: Boolean of whether this user is now botbanned
    """
    botbanned = False
    # Check if user is botbanned
    if await is_botbanned(user_id, guild_id):
        # Remove from botban
        await db.execute("""
            DELETE FROM botbans
            WHERE user_id = %s AND guild_id = %s
        """, user_id, guild_id)
    else:
        await db.execute("""
            INSERT INTO botbans
            (user_id, guild_id)
            VALUES (%s, %s)
        """, user_id, guild_id)
        botbanned = True

    # Invalidate the guild cache
    try:
        del _botban_cache[guild_id]
    except KeyError:
        pass

    return botbanned


@bot.global_auth
async def bot_banned(ctx):
    return not await is_botbanned(ctx.author_id, ctx.guild_id)
