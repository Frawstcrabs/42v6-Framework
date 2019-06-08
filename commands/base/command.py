# -*- coding: utf-8 -*-

from __future__ import annotations

import weakref
import asyncio
from cachetools import TTLCache
from typing import Any, Dict, List, Union, Callable, Awaitable, Optional


class CommandError(Exception):
    """
    Exception used in all parts of command invocation when the execution of one
    must be halted and an error message presented to the user.
    """
    def __init__(self, key, *args, **kwargs):
        """
        Initialise the CommandError object.

        :param key: Key used in response line searching. The line will be
        searched in the context of the command being invoked, in the same way as
        when retrieving a response line normally.
        :param args: Args used to format the response line.
        :param kwargs: Kwargs used to format the response line.
        """
        self.key = key
        self.args = args
        self.kwargs = kwargs


AUTH_CACHE_SIZE = 1000
AUTH_CACHE_TIME = 60


class Command:
    """
    Class representing a discord command, used to control the invocation of the
    function it was constructed with.
    """
    __slots__ = ["id", "_parent", "path", "_function", "_error_responses",
                 "qualified_id", "subcommands", "auth", "_auth_timers",
                 "_converters", "__weakref__"]

    def __init__(self, id_: str, function: Callable[[Context], Awaitable[None]],
                 parent: Optional[Command] = None) -> None:
        """
        Initialise the command object.

        :param id_: Command ID, used for response line searching.
        :param function: Function to be called when the command is invoked
        :param parent: Parent command (will only be None for root)
        """
        self.id = id_
        if parent is not None:
            self._parent: weakref.ReferenceType = weakref.ref(parent)
            self.path = parent.path + f"/command[@id='{self.id}']"
            self.qualified_id = f"{self.parent.qualified_id}.{self.id}"
        else:
            self._parent: None = None
            self.path = f"."
            self.qualified_id = ""

        self.subcommands: Dict[str, Command] = {}

        self._converters: Dict[str, Callable[[str, Context], Any]] = {}
        self.function: Callable[[Context, ...], Awaitable[None]] = function

        self.auth: Dict[Callable[[Context], Awaitable[bool]], str] = {}
        self._auth_timers = {}

    @property
    def parent(self) -> Optional[Command]:
        return self._parent() if self._parent is not None else None

    @property
    def function(self) -> Callable[[Context], Awaitable[None]]:
        return self._function

    @function.setter
    def function(self, func):
        self._function = func
        self._converters = resolve_converters(func)

    def get_output(self, key: str, ctx: Context, numerical_ref: Optional[int]
                   ) -> Union[str, list, dict]:
        """
        Retrieve the response string in this command. This method will search
        recursively through its parents until a matching line ID is found. If
        none is found, raise LanguageError.

        :param key: Line ID to search by
        :param ctx: Command context
        :param numerical_ref: Numerical ref, used in <pluralgroup> tags in
        language files
        :return: Raw response line
        """
        return language.get_output_recursive(self, key, ctx,
                                             numerical_ref=numerical_ref)

    def update_aliases(self, subcommand: Command) -> None:
        """
        Update internal subcommand dict to include the subcommand's aliases.

        :param subcommand: Subcommand to update
        """
        aliases: List[str] = language.get_command_names(subcommand)

        self.subcommands.update({key: subcommand for key in aliases})

    def authorise(self, func: Auth, name: str=None):
        """
        Add an auth function to this command, that will be ran whenever
        this command is invoked. If the function returns false, the command will
        cease execution.

        Note that the auth of a command will always be invoked, even if the
        command function that will be invoked is one of its subcommands.

        :param func: Auth function to invoke
        :param name: Name of the auth function. This will be used when
        searching for error responses in case of the auth failing.
        :return: The command object itself, to allow call chaining.
        """
        if name is None:
            name = func.__name__
        self.auth[func] = name
        self._auth_timers[func] = TTLCache(AUTH_CACHE_SIZE, AUTH_CACHE_TIME)
        return self

    def subcommand(self, id_: Optional[str] = None,
                   auths: List[Auth] = None):
        """
        Add a new subcommand to this command, which will be searched during
        invocation.

        Note that this method must both be called and used as a decorator, e.g.::

            @command.subcommand("id")
            async def my_subcommand(ctx):
                pass

        :param id_: Subcommand ID, used when searching for response strings
        :param auths: A list of auths to add to the new command object
        :return: Newly created command object
        """
        # noinspection PyShadowingNames
        def inner(func: Callable[[Context], Awaitable[None]], parent=self, id_=id_):
            if id_ is None:
                id_ = func.__name__
            cmd = Command(id_, func, parent)
            cmd.authorise(CommandToggle())
            self.subcommands[id_] = cmd
            self.update_aliases(cmd)
            if auths is not None:
                for auth in auths:
                    cmd.authorise(auth)
            return cmd
        return inner

    async def validate_auth(self, ctx: Context) -> Optional[Callable[[Context],
                                                   Awaitable[bool]]]:
        """
        Execute all of the auth functions in this command in order, returning
        the first function that returns False. If all pass, return None.

        :param ctx: Command context
        :return: The auth function that failed, or None if all pass
        """
        auths = list(self.auth.keys())
        auth_checks = await asyncio.gather(*(auth(ctx) for auth in auths))
        for i, check in enumerate(auth_checks):
            if not check:
                # Owners break through auth checks
                if not ctx.author_is_owner:
                    return auths[i]
        return None

    def auth_cooldown(self, auth, user_id):
        """
        Check if the error response for the given auth failing is still in
        cooldown. If it's not, update the internal timer and return False, else
        return True.

        :param auth: Auth function that failed
        :param user_id: ID of user invoking the command
        :return: Boolean of if the error cooldown is in effect
        """
        cache = self._auth_timers[auth]
        if user_id in cache:
            return True
        else:
            cache[user_id] = None
            return False

    async def invoke(self, ctx: Context):
        """Invoke this command.

        This command will search through the first arg in ctx to find if it
        matches one of its subcommands. If so, set the command in ctx to the
        subcommand and execute the subcommand. Else, execute the internal
        command function.

        This method will also check if all of its auths pass, and will return
        the first one that fails. If none fail, return None.

        :param ctx: Command context
        :return: First auth function to fail, or None if all pass
        """
        failed_auth = await self.validate_auth(ctx)
        if failed_auth is not None:
            await ctx.fail_auth(failed_auth)
            return failed_auth

        arg = ctx.next_arg()
        if arg is not None:
            if f"{ctx.lang} {arg}" in self.subcommands:
                sub = self.subcommands[f"{ctx.lang} {arg}"]
                ctx.command = sub
                ctx.remove_arg()
                return await sub.invoke(ctx)
            elif arg in self.subcommands:
                sub = self.subcommands[arg]
                ctx.command = sub
                ctx.remove_arg()
                return await sub.invoke(ctx)

        await self._invoke(ctx)

    async def _invoke(self, ctx: Context):
        """
        Process the command's converters on the command string, then execute
        the internal function. This function handles any CommandErrors raised
        during execution of any of the converters or the internal function
        itself.

        :param ctx: Command context
        """
        async def handle_exception(exc, names):
            line = language.get_coalesce(
                exc.kwargs.pop("relative_to", ctx.command),
                names,
                ctx,
                numerical_ref=exc.kwargs.pop("numerical_ref", None)
            )
            await ctx.post(line.format(*exc.args, **exc.kwargs))

        async def handle_missing_arg(arg_name):
            line = language.get_coalesce(
                ctx.command,
                [f"{arg_name}_ARG_MISSING", "ARG_MISSING"],
                ctx
            )
            await ctx.post(line)

        arg_types = self._converters
        converted_args = []
        kwargs = {}

        for name, (func, default) in list(arg_types.items())[:-2]:
            try:
                converted_args.append(await func(ctx, default))
            except MissingArgError:
                await handle_missing_arg(name)
                return
            except CommandError as e:
                return await handle_exception(e,
                    [f"{name}_{e.key}", e.key, "ARG_ERROR"])

        if arg_types[".star"] is not None:
            (star_name, star_minimum, star_func) = arg_types[".star"]
            arg_count = 0
            while True:
                if ctx.next_arg() is None and arg_count < star_minimum:
                    await handle_missing_arg(star_name)
                    return

                try:
                    converted_args.append(await star_func(ctx, NODEFAULT))
                    arg_count += 1
                except MissingArgError:
                    break
                except CommandError as e:
                    return await handle_exception(e,
                        [f"{star_name}_{e.key}", e.key, "ARG_ERROR"])

        elif arg_types[".remainder"] is not None:
            (r_name, default) = arg_types[".remainder"]
            r_content = ctx.unparsed_content.strip()

            if r_content == "":
                if default == NODEFAULT:
                    await handle_missing_arg(r_name)
                    return
                r_content = default
            kwargs = {r_name: r_content}

        try:
            await self._function(ctx, *converted_args, **kwargs)
        except CommandError as e:
            await ctx.post_line(e.key, *e.args, **e.kwargs)



# Alias some functions
def authorise(func: Auth, name: str=None):
    """
    Alias for the Command.authorise() method, to be used as a decorator while
    declaring a new command.

    This function must be both invoked and used as a decorator, and must be
    placed before the @bot.command() decorator, e.g.::

        @authorise(some_auth)
        @bot.command("id")
        async def command(ctx):
            pass

    :param func: Auth function to add to command
    :param name: Auth name, used when searching for error responses
    :return: Command object itself, to allow multiple decorator calls
    """
    def decorate(cmd: Command):
        return cmd.authorise(func, name)
    return decorate


from .converters import resolve_converters, MissingArgError, NODEFAULT
from .toggle import CommandToggle
from .context import Context
Auth = Callable[[Context], Awaitable[bool]]
from . import language
