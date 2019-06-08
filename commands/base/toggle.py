# -*- coding: utf-8 -*-
from typing import List, Optional

import cachetools
from . import db

_toggle_cache = cachetools.LFUCache(100)


async def is_toggled(guild_id: Optional[int], path: str) -> bool:
    """
    Return if the given command path is disabled in the given guild ID.

    :param guild_id: ID of guild to search in
    :param path: Command path
    :return: Boolean of if the command is disabled
    """
    if guild_id is None:
        return False

    try:
        return guild_id in _toggle_cache[path]

    except KeyError:
        ret = await db.fetchall("""
            SELECT guild_id FROM toggles
            WHERE command = %s
        """, path)

        ret = [row[0] for row in ret]

        _toggle_cache[path] = ret

        return guild_id in _toggle_cache[path]


async def get_guild_toggles(guild_id: int, path: str = "") -> List[str]:
    """
    Retrieve a list of all disabled commands that match or are subcommands of
    the given command path in the given guild.

    :param guild_id: ID of guild to search in
    :param path: Root command path to search for
    :return: List of disabled command paths
    """
    ret = await db.fetchall("""
        SELECT command FROM toggles
        WHERE guild_id = %s
    """, guild_id)

    path = path.replace("*", "")

    return [row[0] for row in ret if path in row[0]]


async def toggle_elements(guild_id: int, *elements: str):
    """
    Toggle the given command paths in the given guild, such that if the command
    was disabled, it is enabled, and vice versa.

    :param guild_id: ID of guild to search in
    :param elements: Command paths to toggle
    """
    args = [(guild_id, e) for e in elements]

    await db.executemany("""
        CALL toggle_toggle(%s, %s);
    """, *args)

    for path in elements:
        if path in _toggle_cache:
            try:
                _toggle_cache[path].remove(guild_id)
            except ValueError:
                _toggle_cache[path].append(guild_id)


async def enable_elements(guild_id: int, *elements: str):
    """
    Set all of the given command paths to enabled in the given guild.

    :param guild_id: ID of guild to enable in
    :param elements: Command paths to enable
    """
    args = [(guild_id, e) for e in elements]

    await db.executemany("""
        DELETE FROM toggles
        WHERE guild_id = %s AND command = %s;  
    """, *args)

    for path in elements:
        if path in _toggle_cache and \
                guild_id not in _toggle_cache[path]:
            _toggle_cache[path].append(guild_id)


async def disable_elements(guild_id: int, *elements: str):
    """
    Set all of the given command paths to disabled in the given guild.

    :param guild_id: ID of guild to disable in
    :param elements: Command paths to disable
    """
    args = [(guild_id, e) for e in elements]

    await db.executemany("""
        INSERT IGNORE INTO toggles
        (guild_id, command)
        VALUES (%s, %s);
    """, *args)

    for path in elements:
        if path in _toggle_cache:
            try:
                _toggle_cache[path].remove(guild_id)
            except ValueError:
                pass


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class CommandToggle(metaclass=Singleton):
    """
    Auth class added to all layers of command to check if the command has
    been disabled in the server it's being called in.
    """
    __slots__ = []
    __name__ = "toggle"
    @staticmethod
    async def __call__(ctx):
        return await is_toggled(ctx.guild_id, ctx.command.qualified_id)
