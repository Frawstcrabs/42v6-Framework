# -*- coding: utf-8 -*-

from discord import Member
from .converters import add_converter
from .converters import ConverterError
from .utils import get_member


# some converters for base types

# noinspection PyUnusedLocal
@add_converter(str)
def convert_str(arg, ctx):
    return arg

# noinspection PyUnusedLocal
@add_converter(int)
def convert_int(arg, ctx):
    try:
        return int(arg)
    except ValueError:
        raise ConverterError("INT_RESOLVE_error") from None

# noinspection PyUnusedLocal
@add_converter(float)
def convert_float(arg, ctx):
    try:
        return float(arg)
    except ValueError:
        raise ConverterError("FLOAT_RESOLVE_error") from None

# noinspection PyUnusedLocal
@add_converter(None, type(None))
def convert_none(arg, ctx):
    return None


@add_converter(Member)
async def member_converter(arg, ctx):
    if ctx.guild is None:
        raise RuntimeError("Cannot use Member resolver in DM")
    member = await get_member(arg, ctx)
    if member is None:
        raise ConverterError("MEMBER_RESOLVE_not_found")
    return member
