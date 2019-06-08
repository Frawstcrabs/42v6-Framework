# -*- coding: utf-8 -*-

from __future__ import annotations

import cachetools
from typing import List, Optional

from . import db
from .client import bot


# Internal cache of guild invokers, to reduce unnecessary database queries
_invoker_cache = cachetools.LFUCache(100)


async def get_alias(guild_id: int) -> List[str]:
    """
    Search the database for any invoker aliases in this guild.

    :param guild_id: ID of guild to search
    :return: List of all accepted invokers, including the default invoker and
    ping invokers
    """
    if guild_id not in _invoker_cache:
        ret = await db.fetchall("""
            SELECT callstr FROM invokers
            WHERE guild_id = %s;
        """, guild_id)
        ret = bot.ping_invokers + [row[0] for row in ret]

        if None in ret:
            ret.remove(None)
        else:
            ret = [bot.invoker] + ret
        _invoker_cache[guild_id] = ret

    return _invoker_cache[guild_id]


async def toggle_alias(guild_id: int, invoker: Optional[str]) -> bool:
    """
    Toggles the given invoker in the given guild.

    :param guild_id: ID of guild to toggle invoker in
    :param invoker: Invoker to toggle
    :return: Boolean of whether this invoker was enabled in the guild
    """
    guild_invokers = await get_alias(guild_id)
    added = invoker not in guild_invokers
    if added:
        _invoker_cache[guild_id].append(invoker)
        if invoker == bot.invoker:
            # need to remove null from db
            await db.execute("""
                DELETE FROM invokers
                WHERE guild_id = %s
                  AND callstr IS NULL;
            """, guild_id)
        else:
            await db.execute("""
                INSERT INTO invokers
                VALUES (%s, %s);
            """, guild_id, invoker)
    else:
        if invoker == bot.invoker:
            # we need to insert null into the db
            # to signal the default invoker is removed
            await db.execute("""
                INSERT INTO invokers
                VALUES (%s, NULL);
            """, guild_id)
        else:
            await db.execute("""
                DELETE FROM invokers
                WHERE guild_id = %s
                  AND callstr = %s;
            """, guild_id, invoker)
    del _invoker_cache[guild_id]
    return added


@bot.on_ready
async def set_ping_invokers():
    bot.ping_invokers = [f"<@{bot.user.id}>", f"<@!{bot.user.id}>"]
