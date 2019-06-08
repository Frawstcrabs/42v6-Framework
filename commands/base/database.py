# -*- coding: utf-8 -*-
from typing import Tuple, Any

import aiomysql
import asyncio
import json


class Database:
    """
    Class used to represent the database connection used by the bot.
    """
    __slots__ = []
    pool = None
    @classmethod
    async def _make(cls, **credentials):
        """
        Initialise the database class.

        :param credentials: MySQL database credentials.
        """
        cls.pool = await aiomysql.create_pool(**credentials, autocommit=True)

    @classmethod
    async def fetchone(cls, query, *data):
        """
        Fetch a single row from the given query, using the given parameters for
        prepared statements. If the resulting row only contains one item, return
        said item, else return the full row. If no row is found, return None.

        :param query: SQL query to execute
        :param data: Arguments for prepared statements in query
        :return: Fetched row from database
        """
        async with cls.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, data)
                ret = await cur.fetchone()
                if ret is None:
                    return ret
                elif len(ret) == 1:
                    return ret[0]
                else:
                    return ret

    @classmethod
    async def fetchall(cls, query, *data):
        """
        Fetch all rows from the given query, using the given parameters for
        prepared statements. If no rows are found, return None.

        :param query: SQL query to execute
        :param data: Arguments for prepared statements in query
        :return: Fetched rows from database
        """
        async with cls.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, data)
                return await cur.fetchall()

    @classmethod
    async def execute(cls, query, *data) -> int:
        """
        Execute the given query.

        :param query: SQL query to execute
        :param data: Arguments for prepared statements in query
        """
        async with cls.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, data)
                return cur.rowcount

    @classmethod
    async def executemany(cls, query, *data_groups: Tuple[Any, ...]) -> int:
        """
        Execute the given query multiple times, once for each entry in the
        data_groups parameter.

        :param query: SQL query to execute
        :param data_groups: List of tuples of arguments to use in prepared
        statements
        """
        async with cls.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(query, data_groups)
                return cur.rowcount


with open("config.json") as f:
    # need to load the config file again to get credentials
    config = json.load(f)
    asyncio.get_event_loop().run_until_complete(
        Database._make(**config["db_credentials"])
    )
