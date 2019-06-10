# -*- coding: utf-8 -*-

from __future__ import annotations

import re
import time
from unittest.mock import sentinel

from typing import List, Union, Callable, Awaitable, Optional
from discord import (DMChannel, Embed, GroupChannel, Guild, Message,
                     Member, User, TextChannel)
from discord.abc import Messageable

NOTSET = sentinel.NOTSET


class Context:
    """
    Class used as a container for all necessary objects during command
    invocation.
    """
    __slots__ = ["bot", "message", "message_id", "author_id", "guild_id",
                 "channel_id", "command", "unparsed_content", "__next_arg_len",
                 "invoker", "_last_message", "_last_message_id", "_lang",
                 "data", "start_time"]

    def __init__(self, bot_: Bot, message: Message,
                 command: Command, content: str,
                 invoker: str) -> None:
        """
        Initialise the context object.
        This constructor should not be called directly, and the async
        staticmethod Context.make() should be used instead, so that lang can be
        properly resolved.

        :param bot_: Bot object
        :param message: Message object of the command
        :param command: Command object being executed
        :param content: Current message
        :param invoker: Invoker used when the command was executed
        """
        self.bot: Bot = bot_
        self.message: Message = message
        self.message_id: int = message.id
        self.author_id: int = message.author.id
        self.guild_id: Optional[int] = \
            message.guild.id if message.guild is not None else None
        self.channel_id: int = message.channel.id

        self.command: Command = command
        self.unparsed_content = content
        self.__next_arg_len: Optional[int] = None
        self.invoker = invoker
        self._last_message: Optional[Message] = None
        self._last_message_id: Optional[int] = None

        self._lang: Optional[str] = None

        self.start_time = time.time()

    @property
    def last_message(self):
        return self._last_message

    @last_message.setter
    def last_message(self, msg):
        if msg is None:
            self._last_message = None
            self._last_message_id = None
        else:
            self._last_message = msg
            self._last_message_id = msg.id

    @property
    def last_message_id(self):
        return self._last_message_id

    @property
    def guild(self) -> Optional[Guild]:
        # return msg.guild if (msg := self._message()) is not None else None
        msg = self.message
        return msg.guild if msg is not None else None

    @property
    def channel(self) -> Union[TextChannel, GroupChannel,
                               DMChannel, None]:
        # return msg.channel if (msg := self._message()) is not None else None
        msg = self.message
        return msg.channel if msg is not None else None

    @property
    def author(self) -> Union[User, Member]:
        # return msg.author if (msg := self._message()) is not None else None
        msg = self.message
        return msg.author if msg is not None else None

    @property
    def lang(self) -> str:
        return self._lang

    @property
    def author_is_owner(self) -> bool:
        return self.author_id in self.bot.coowners

    @property
    def is_private(self) -> bool:
        return self.guild_id is None

    async def _resolve_lang(self):
        """|coro|

        Resolve the language that response lines should be sent in, depending
        on the guild/channel the command is being executed in."""
        self._lang = await language.get_lang(self.guild_id, self.channel_id)

    @classmethod
    async def make(cls, bot_: Bot, message: Message,
                   command: Command, content: str,
                   invoker: str) -> Context:
        """Create a new Context object.

        Create a new Context object. This will also add a space to the end of
        the invoker used if it is longer than 3 characters or ends with a latin
        letter, as well as resolving lang depending on channel/guild.

        :param bot_: Bot object
        :param message: Message object
        :param command: Command object being executed
        :param content: Current message content
        :param invoker: Invoker used to execute command
        :return: Newly created context object
        """
        if len(invoker) > 3 or re.match(".*[a-z]$", invoker, re.I):
            invoker += " "
        ctx = cls(bot_, message, command, content, invoker)
        await ctx._resolve_lang()
        return ctx

    def next_arg(self):
        """Retrieve the next argument in the command string.

        Retrieve the next argument in the command string. If the next argument
        is wrapped in quotes, the quotes will be removed and everything inside
        will be returned. Note that this method will not remove the arg, and
        this must be done manually via Context.remove_arg().

        :return: Next arg in message content
        """
        arg, new_content = get_next_arg(self.unparsed_content)
        self.__next_arg_len = len(self.unparsed_content) - len(new_content)
        return arg

    def list_args(self, limit: int):
        """
        Retrieves a list of `limit' args from the command string without
        removing them. This can be used to allow lookahead when parsing
        commands in converters. If the number of args requested is greater
        than the amount in the command string, the remaining places will be
        filled with None objects.

        :param limit: Number of args to return
        :return: List of next args in command string
        """
        if limit <= 0:
            raise ValueError(f"Invalid number of args: {limit}")
        ret = []
        temp_content = self.unparsed_content
        for _ in range(limit):
            arg, temp_content = get_next_arg(temp_content)
            ret.append(arg)
        return ret

    def remove_arg(self):
        """Remove the first arg in the command string."""
        if self.__next_arg_len is None:
            self.next_arg()
        self.unparsed_content = self.unparsed_content[self.__next_arg_len:]
        self.__next_arg_len = None

    async def fail_auth(self, auth: Callable[[Context], Awaitable[bool]]
                        ) -> None:
        """
        Process a failed auth command by sending an error message to the user.

        :param auth: Failed auth command
        """
        if self.command.auth_cooldown(auth, self.author_id):
            return

        auth_name = self.command.auth.get(auth, auth.__name__)
        try:
            line = self.get_output(f"error_{auth_name}")
        except language.LanguageError:
            try:
                msg = self.get_output(f"permission_{auth_name}")
            except language.LanguageError:
                msg = ""

            line = self.get_output(f"error_authority", auth_name)
            line += "\n" + msg

        await self.post(line)

    async def send_to(self, dest: Messageable, content: Optional[str] = None,
                      *, embed: Optional[Embed] = None) -> Message:
        """
        Send a new message to the given destination. This will also update the
        last_message attribute of this object.

        :param dest: Messageable object to send to
        :param content: Message content
        :param embed: Optional message embed
        :return: Newly created message object
        """
        self.last_message = await self.bot.send_message(dest, content,
                                                        embed=embed)
        return self.last_message

    async def post(self, content: Optional[str] = None, *,
                   embed: Optional[Embed] = None) -> Message:
        """
        Send a new message to the channel the command was invoked in. This will
        also update the last_message attribute of this object.

        :param content: Message content
        :param embed: Optional message embed
        :return: Newly created message object
        """
        return await self.send_to(self.channel, content, embed=embed)

    async def whisper(self, content: Optional[str] = None, *,
                      embed: Optional[Embed] = None) -> Message:
        """
        Send a new message to the user that invoked this command. This will
        also update the last_message attribute of this object.

        :param content: Message content
        :param embed: Optional message embed
        :return: Newly created message object
        """
        return await self.send_to(self.author, content, embed=embed)

    async def replace(self, content: Optional[str] = None, *,
                      embed: Optional[Embed] = None) -> Message:
        """
        Delete the message that invoked this command, then send a new message to
        its channel. This will also update the last_message attribute of this
        object.

        :param content: Message content
        :param embed: Optional message embed
        :return: Newly created message object
        """
        await self.bot.delete_message(self.message)
        return await self.send_to(self.channel, content, embed=embed)

    async def edit(self, *, content: Union[str, None] = NOTSET,
                   embed: Union[Embed, None] = NOTSET, **params) -> Message:
        """
        Edit the most recently sent message by the bot while executing this
        command. This will also update the last_message attribute of this
        object. If no message has been sent yet, raise RuntimeError.

        :param content: (optional) New message content
        :param embed: (optional) New embed
        :param params: Other parameters sent to bot.edit_message
        :return: Message that was edited
        """
        if self._last_message is None:
            raise RuntimeError("No message sent yet")
        if content is not NOTSET:
            params["content"] = content
        if embed is not NOTSET:
            params["embed"] = embed
        await self.bot.edit_message(self.last_message, **params)
        return self.last_message

    def get_raw_output(self, key: str, *,
                       relative_to: Optional[Command] = None,
                       numerical_ref: Optional[int] = None) -> str:
        """
        Search for the response string with the given key. This method will
        search from the parameter relative_to then recursively search its
        parents until a matching line is found. If none exist, raise
        LanguageError.

        :param key: ID of line to search
        :param relative_to: Command object to search from. If set to None,
        search from the command currently being invoked.
        :param numerical_ref: Numerical ref used in <pluralgroup> tags in
        language files.
        :return: Raw response string
        """
        if relative_to is None:
            relative_to = self.command

        line = relative_to.get_output(key, self, numerical_ref=numerical_ref)
        return line

    def get_output(self, key: str, *args,
                   relative_to: Optional[Command] = None,
                   numerical_ref: Optional[int] = None, **kwargs) -> str:
        """
        Search for a response string with the given key, then call str.format()
        on the result using the *args and **kwargs parameters. This method works
        by invoking Command.get_raw_output().

        :param key: ID of line to search
        :param args: Positional args used to format line
        :param relative_to: Command object to search from. If set to None,
        search from the command currently being invoked.
        :param numerical_ref: Numerical ref used in <pluralgroup> tags in
        language files.
        :param kwargs: Keyword args used to format line
        :return: Formatted response line
        """
        line = self.get_raw_output(key, relative_to=relative_to,
                                   numerical_ref=numerical_ref)

        return line.format(*args, **kwargs)

    async def send_line_to(self, dest: Messageable, key: str, *args,
                           relative_to: Optional[Command] = None,
                           numerical_ref: Optional[int] = None, **kwargs
                           ) -> Message:
        """
        Send a new message to dest by searching for the response line with the
        matching key and formatting it. This method works by invoking
        Context.get_output() and Context.send_to().

        :param dest: Messageable object to send to
        :param key: ID of line to search
        :param args: Positional args used to format line
        :param relative_to: Command object to search from. If set to None,
        search from the command currently being invoked.
        :param numerical_ref: Numerical ref used in <pluralgroup> tags in
        language files.
        :param kwargs: Keyword args used to format line
        :return: Formatted response line
        """
        line = self.get_output(key, *args, relative_to=relative_to,
                               numerical_ref=numerical_ref, **kwargs)
        return await self.send_to(dest, line)

    async def post_line(self, key: str, *args,
                        relative_to: Optional[Command] = None,
                        numerical_ref: Optional[int] = None, **kwargs
                        ) -> Message:
        """
        Send a new message to the channel the command was invoked in, by
        searching for the response line with the matching key and formatting it.
        This method works by invoking Context.get_output() and Context.post().

        :param key: ID of line to search
        :param args: Positional args used to format line
        :param relative_to: Command object to search from. If set to None,
        search from the command currently being invoked.
        :param numerical_ref: Numerical ref used in <pluralgroup> tags in
        language files.
        :param kwargs: Keyword args used to format line
        :return: Formatted response line
        """
        return await self.send_line_to(self.channel, key, *args,
                                       relative_to=relative_to,
                                       numerical_ref=numerical_ref, **kwargs)

    async def whisper_line(self, key: str, *args,
                           relative_to: Optional[Command] = None,
                           numerical_ref: Optional[int] = None, **kwargs
                           ) -> Message:
        """
        Send a new message to the command invoker's DMs, by searching for the
        response line with the matching key and formatting it. This method works
        by invoking Context.get_output() and Context.whisper().

        :param key: ID of line to search
        :param args: Positional args used to format line
        :param relative_to: Command object to search from. If set to None,
        search from the command currently being invoked.
        :param numerical_ref: Numerical ref used in <pluralgroup> tags in
        language files.
        :param kwargs: Keyword args used to format line
        :return: Formatted response line
        """
        return await self.send_line_to(self.author, key, *args,
                                       relative_to=relative_to,
                                       numerical_ref=numerical_ref, **kwargs)

    async def replace_line(self, key: str, *args,
                           relative_to: Optional[Command] = None,
                           numerical_ref: Optional[int] = None, **kwargs
                           ) -> Message:
        """
        Delete the message that invoked this command, then send a new message
        with the appropriate formatted response string.
        This method works by invoking Context.get_output() and
        Context.replace().

        :param key: ID of line to search
        :param args: Positional args used to format line
        :param relative_to: Command object to search from. If set to None,
        search from the command currently being invoked.
        :param numerical_ref: Numerical ref used in <pluralgroup> tags in
        language files.
        :param kwargs: Keyword args used to format line
        :return: Formatted response line
        """
        await self.bot.delete_message(self.message)
        return await self.send_line_to(self.channel, key, *args,
                                       relative_to=relative_to,
                                       numerical_ref=numerical_ref, **kwargs)

    async def edit_line(self, key: str, *args,
                        relative_to: Optional[Command] = None,
                        numerical_ref: Optional[int] = None, **kwargs
                        ) -> Message:
        """
        Edits the most recently sent message in this context with the response
        string with the given key. This method works by calling
        Context.get_output() and Context.edit(). If no message has been sent,
        raise RuntimeError.

        :param key: ID of line to search
        :param args: Positional args used to format line
        :param relative_to: Command object to search from. If set to None,
        search from the command currently being invoked.
        :param numerical_ref: Numerical ref used in <pluralgroup> tags in
        language files.
        :param kwargs: Keyword args used to format line
        :return: Formatted response line
        """
        line = self.get_output(key, *args, relative_to=relative_to,
                               numerical_ref=numerical_ref, **kwargs)
        return await self.edit(content=line)


from .utils import get_next_arg
from .command import Command
from .client import Bot
from . import language
