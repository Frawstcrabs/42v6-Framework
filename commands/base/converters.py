# -*- coding: utf-8 -*-

from __future__ import annotations

import inspect
from asyncio import iscoroutinefunction
from unittest.mock import sentinel
from .command import CommandError


_converters = {}
NODEFAULT = sentinel.NODEFAULT


class ConverterError(CommandError):
    """
    Exception inheriting from CommandError, intended for converters to use when
    an arg cannot be parsed.
    """
    pass


class MissingArgError(Exception):
    """
    Exception used to signal that the context object in a converter contains
    too few args and cannot continue.
    """
    pass


def _retrieve_simple_convert(t):
    """
    Test if the object contains a convert_arg method to be used as a converter
    and return it.
    If one is not found, raise TypeError.

    :param t: Possible converter type
    :return: Converter function
    """
    try:
        meth = t.convert_arg
    except (AttributeError, TypeError):
        raise TypeError(f"Invalid converter type {t}") from None

    return add_converter()(meth)


def _retrieve_convert_method(t):
    """
    Test if the object contains a convert_arg_manual method to be used as a
    manual converter and return it.
    If one is not found, test for a convert_arg method instead.
    If that is also not found, raise TypeError.

    :param t: Possible converter type
    :return: Converter function
    """
    try:
        meth = t.convert_arg_manual
    except (AttributeError, TypeError):
        return _retrieve_simple_convert(t)

    if not iscoroutinefunction(meth):
        raise TypeError("Manual converter must be a coroutine")

    return meth


def _union_converter(types):
    """
    Create a converter function to be used for typing.Union[] types.
    Each of the converters in the Union[] object will be tested in order,
    returning the first one that does not raise a CommandError. If all
    converters raise an error, raise a special union commanderror. If any
    converter raises a MissingArgError, reraise. If Nonetype is encountered,
    return default if exists, else raise MissingArgError.

    :param types: Types found in the Union[] object
    :return: Converter function
    """
    convert_funcs = []
    for t in types:
        if t in [None, type(None)]:
            convert_funcs.append(None)
        else:
            convert_funcs.append(resolve_converter_function(t))

    async def convert_arg(ctx, default):
        for func in convert_funcs:
            if func is None:
                if default == NODEFAULT:
                    return None
                return default

            try:
                return await func(ctx, NODEFAULT)
            except MissingArgError as e:
                if default == NODEFAULT:
                    raise e from None
                return default
            except CommandError:
                pass
        raise ConverterError("UNION_RESOLVE_error") from None
    return add_manual_converter()(convert_arg)


def resolve_converter_function(t):
    """
    Resolve the converter function to use for the given type. The following
    types are supported:
    - If given inspect.Parameter.empty, return the converter for the string
    type.
    - If given an object from the typing module containing 2 or more objects,
    return a special union converter function. If it contains one, use the type
    contained in it and continue.
    - If the given object has been passed in as one of the arguments in the
    converter decorators, return the function that it was decorating.
    - If the given object has a convert_arg_manual method, return it.
    - If the given object has a convert_arg method, return it.
    - If given a function decorated with one of the converter decorators, return
    it.
    - Else, raise TypeError.

    :param t: Possible converter type
    :return: Converter function
    """
    try:
        if len(t.__args__) == 1:
            t = t.__args__[0]
        elif len(t.__args__) >= 2:
            return _union_converter(t.__args__)
    except AttributeError:
        pass

    if t == inspect.Parameter.empty:
        return _converters[str]
    elif t in _converters:
        return _converters[t]

    try:
        return _retrieve_convert_method(t)
    except TypeError:
        pass

    if callable(t):
        if not getattr(t, "_converter", False):
            raise TypeError("Function converters must be decorated")
        return t

    raise TypeError(f"Invalid converter type {t}")


def resolve_converters(function):
    """
    Parse a function's signature for annotations, resolving all converter
    functions from them. Returns an ordered dict of parameter name to converter
    data.

    :param function: Function to parse
    :return: Dict of param name to converter data
    """
    arg_types = {}
    star = None
    remainder = None
    sig = inspect.signature(function)
    rcf = resolve_converter_function

    for param in list(sig.parameters.values())[1:]:
        name = param.name
        func = param.annotation
        if isinstance(func, str):
            # If this errors, we want the user to know
            func = eval(func, function.__globals__)
        default = param.default
        if default == inspect.Parameter.empty:
            default = NODEFAULT

        if param.kind == param.POSITIONAL_OR_KEYWORD:
            arg_types[name] = (rcf(func), default)
        elif param.kind == param.VAR_POSITIONAL:
            if isinstance(func, Required):
                star = (name, func._min, rcf(func._converter))
            else:
                star = (name, 0, rcf(func))
        elif param.kind == param.KEYWORD_ONLY:
            if star is not None:
                raise TypeError(
                    "Cannot both have star param and remainder param")
            elif remainder is not None:
                raise TypeError("Cannot have multiple remainder params")
            remainder = (name, default)
        elif param.kind == param.VAR_KEYWORD:
            raise TypeError("Variable keyword arguments not supported")

    arg_types[".star"] = star
    arg_types[".remainder"] = remainder
    return arg_types


def add_converter(*types):
    """
    Create a new simple converter function and return it.
    This function must both be called and used as a decorator, e.g.::

        @add_decorator()
        def my_decorator(arg, ctx):
            pass

    Any types passed into the decorator will be treated specially by the
    framework, in that whenever that type is used as a converter, the function
    being decorated will be used as the converter instead.

    The converter function returned by this function can also be used in as a
    converter in command annotations, and only functions decorated by this
    function can be used in this way.

    :param types: Optional types that should be represented by the decorated
    function
    :return: Converter function
    """
    def decorate(func):
        async def simple_converter(ctx, default):
            arg = ctx.next_arg()
            if arg is None:
                if default == NODEFAULT:
                    raise MissingArgError
                return default

            try:
                if iscoroutinefunction(func):
                    ret = await func(arg, ctx)
                else:
                    ret = func(arg, ctx)
            except CommandError:
                raise
            else:
                ctx.remove_arg()
            return ret
        return add_manual_converter(*types)(simple_converter)
    return decorate


def add_manual_converter(*types):
    """
    Create a new manual converter function and return it.
    This function must both be called and used as a decorator, e.g.::

        @add_manual_decorator()
        def my_manual_decorator(ctx, default):
            pass

    Any arguments that the converter wants to handle must be obtained from the
    passed context object and popped once used. If the conversion is
    unsuccessful, the argument should not be popped and a CommandError or one of
    its subclasses should be raised.

    The default arg is passed to be return when the necessary arguments are
    missing from context. This can also be a special sentinel value, NODEFAULT,
    which signals that a MissingArgError should be raised instead.

    Any types passed into the decorator will be treated specially by the
    framework, in that whenever that type is used as a converter, the function
    being decorated will be used as the converter instead.

    The converter function returned by this function can also be used in as a
    converter in command annotations, and only functions decorated by this
    function can be used in this way.

    :param types: Optional types that should be represented by the decorated
    function
    :return: Converter function
    """
    def decorate(func):
        if not iscoroutinefunction(func):
            raise TypeError("manual converter must be a coroutine")
        func._converter = True
        for t in types:
            _converters[t] = func
        return func
    return decorate


class _MetaConverter(type):
    def __getitem__(cls, *args, **kwargs):
        return cls(*args, **kwargs)


class MetaConverter(metaclass=_MetaConverter):
    """
    Class that allows construction via Type() or Type[].
    """
    pass


class Greedy(MetaConverter):
    """
    Converter class that processes as many args as possible, until its
    internal converter raises a CommandError. It will try to process the
    arguments successfully at least once, else the default value will be
    returned.
    """
    __slots__ = ["_func"]

    def __init__(self, t):
        self._func = resolve_converter_function(t)

    async def convert_arg_manual(self, ctx, default):
        ret = []
        while True:
            try:
                ret.append(await self._func(ctx, NODEFAULT))
            except (MissingArgError, CommandError) as e:
                if ret:
                    return ret
                # no args parsed, return default
                if default == NODEFAULT:
                    raise e from None
                return default


class Required(MetaConverter):
    """
    Special converter type only used in *args parameters in command functions.
    It signals that a minimum number of items must be passed into the parameter,
    or the parameter will be treated as missing and an error will be reported to
    the user. By default, the minimum value is 1.
    """
    __slots__ = ["_min", "_converter"]

    def __init__(self, a, b=None):
        """
        Initialise the Required[] object.

        Can either be initialised as Required[Type] or Required[n, Type], where
        n is the minimum number of values requested for *args.
        """
        if b is None:
            self._min = 1
            self._converter = a
        else:
            if not isinstance(a, int):
                raise TypeError("Minimum param in Required[] must be int, "
                               f"not {type(a)}")
            self._min = a
            self._converter = b
