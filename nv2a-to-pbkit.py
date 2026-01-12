#!/usr/bin/env python3

# ruff: noqa: T201 `print` found
# ruff: noqa: PLR2004 Magic value used in comparison
# ruff: noqa: UP031 Use format specifiers instead of percent format

from __future__ import annotations

import argparse
import os
import re
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass

# Maximum number of pgraph commands per pb_begin/end block
MAX_COMMANDS_PER_FLUSH = 32

_HEX_VALUE = r"0x[0-9a-fA-F]+"
_FLOAT_VALUE = r"[-+0-9.]+"
# fmt: off

# nv2a_pgraph_method 0: 0x97 -> 0x1800 0x11000F
# nv2a_pgraph_method 0: 0x97 -> 0x1788 NV097_SET_VERTEX_DATA_ARRAY_FORMAT[40] 0x1402
# nv2a_pgraph_method 1: 0x39 -> 0x0 (0x14cf0)
_PGRAPH_METHOD_RE = re.compile(
    r"nv2a_pgraph_method (\d+):\s+(" + _HEX_VALUE + r") -> (" + _HEX_VALUE + r")\s+(?:(\S+)\s+)?\(?(" + _HEX_VALUE + r")\)?"
)

# nv2a_pgraph_method 0: NV20_KELVIN_PRIMITIVE<0x97> -> NV097_SET_TRANSFORM_CONSTANT_LOAD<0x1EA4> (0x62)
# nv2a_pgraph_method 0: NV20_KELVIN_PRIMITIVE<0x97> -> NV097_SET_TRANSFORM_CONSTANT[1]<0xB84> (0x00000000 => 0.000000)
# nv2a_pgraph_method 0: 0x97 -> NV097_SET_TEXGEN_PLANE_S@3[1]<0x904> (0x00000000 => 0)
# nv2a_pgraph_method 0: NV20_KELVIN_PRIMITIVE<0x97> -> NV097_SET_BEGIN_END<0x17fc> (NV097_SET_BEGIN_END_OP_END<0x0>)
# nv2a_pgraph_method 0: 0x97 -> NV097_SET_OBJECT<0x0> (0x000149C0 => 84416)
# nv2a_pgraph_method 2: 0x9f -> NV09F_SET_OPERATION<0x2fc> (SRCCOPY)
_PRETTY_PGRAPH_METHOD_RE = re.compile(
    r"nv2a_pgraph_method (\d+):\s+(?:\S*<)?(" + _HEX_VALUE + r")>?\s+->\s+(\S+)<(" + _HEX_VALUE + r")>\s+\((.+)\)"
)

# 0x00000000 => 0.000000
_PRETTY_ARGUMENT_FLOAT_RE = re.compile(
    r"(" + _HEX_VALUE + r")\s+=>\s+(" + _FLOAT_VALUE + r")"
)
# {BLUE:00 0.000000, GREEN:00 0.000000, RED:00 0.000000, ALPHA:00 0.000000} <0x0>
PRETTY_ARGUMENT_BITVECTOR_RE = re.compile(
    r"(\{.+})\s+<(" + _HEX_VALUE + r")>"
)
# NV097_SET_BEGIN_END_OP_TRIANGLE_FAN<0x7>
_PRETTY_ARGUMENT_NAMED_VALUE_RE = re.compile(r"(\w+)<(" + _HEX_VALUE + r")>")
# 0x3f800000
_PRETTY_ARGUMENT_HEX_VALUE_RE = re.compile(r"(" + _HEX_VALUE + r")")

# 84416 <0x149c0>
_PRETTY_ARGUMENT_RAW_VALUE_RE = re.compile(r"\S+\s+<(" + _HEX_VALUE + r")>")

# nv2a_pgraph_method_unhandled 0: 0x97 -> 0x03b8 0x0
_UNHANDLED_METHOD_RE = re.compile(
    r"nv2a_pgraph_method_unhandled\s+(\d+):\s+(" + _HEX_VALUE + r")\s+->\s+(" + _HEX_VALUE + r")\s+(" + _HEX_VALUE + r")"
)
# fmt: on


BEGIN_END = 0x17FC

STATELESS_COMMANDS = {
    0x00000100,  # NV097_NO_OPERATION
    0x00000110,  # NV097_WAIT_FOR_IDLE
    0x00000120,  # NV097_SET_FLIP_READ
    0x0000012C,  # NV097_FLIP_INCREMENT_WRITE
    0x00000130,  # NV097_FLIP_STALL
    0x00001710,  # NV097_BREAK_VERTEX_BUFFER_CACHE
    0x000017D0,  # NV097_GET_REPORT
    0x000017FC,  # NV097_SET_BEGIN_END
    0x00001D70,  # NV097_BACK_END_WRITE_SEMAPHORE_RELEASE
}

# These commands are stateful but specify memory addresses that are probably not portable.
NON_PORTABLE_STATEFUL_COMMANDS = {
    0x00000210,  # NV097_SET_SURFACE_COLOR_OFFSET
    0x00000214,  # NV097_SET_SURFACE_ZETA_OFFSET
    0x00001B00,  # NV097_SET_TEXTURE_OFFSET
    0x00001B40,  # NV097_SET_TEXTURE_OFFSET
    0x00001B80,  # NV097_SET_TEXTURE_OFFSET
    0x00001BC0,  # NV097_SET_TEXTURE_OFFSET
    0x00001720,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x00001724,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x00001728,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x0000172C,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x00001730,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x00001734,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x00001738,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x0000173C,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x00001740,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x00001744,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x00001748,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x0000174C,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x00001750,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x00001754,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x00001758,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x0000175C,  # NV097_SET_VERTEX_DATA_ARRAY_OFFSET
    0x000017C8,  # NV097_CLEAR_REPORT_VALUE - If no report value was set this will trigger an exception.
}


def push1_pbkit(
    prefix: str | None,
    nv_op: int,
    nv_op_name: str | None,
    nv_param: int,
    descr: str | None = None,
) -> str:
    if prefix is None:
        prefix = ""
    op_name = "" if nv_op_name is None else f"/* {nv_op_name} */"
    if descr is None:
        descr = ""

    return f"{prefix}p = pb_push1(p, 0x{nv_op:X} {op_name}, 0x{nv_param:X});{descr}"


def push1f_pbkit(prefix: str | None, nv_op: int, nv_op_name: str, nv_param: float) -> str:
    if prefix is None:
        prefix = ""
    return f"{prefix}p = pb_push1(p, 0x{nv_op:X} /*{nv_op_name}*/, {nv_param});"


def push_pbkitplusplus(
    prefix: str | None,
    nv_op: int,
    nv_op_name: str | None,
    nv_param: int,
    descr: str | None = None,
) -> str:
    if prefix is None:
        prefix = ""
    op_name = "" if nv_op_name is None else f"/* {nv_op_name} */"
    if descr is None:
        descr = ""

    return f"{prefix}Pushbuffer::Push(0x{nv_op:X} {op_name}, 0x{nv_param:X});{descr}"


def pushf_pbkitplusplus(
    prefix: str | None,
    nv_op: int,
    nv_op_name: str | None,
    nv_param: float,
    descr: str | None = None,
) -> str:
    if prefix is None:
        prefix = ""
    op_name = "" if nv_op_name is None else f"/* {nv_op_name} */"
    if descr is None:
        descr = ""

    return f"{prefix}Pushbuffer::Push(0x{nv_op:X} {op_name}, {nv_param});{descr}"


def push1_to_pbkit(
    prefix: str | None,
    nv_channel: int,
    nv_class: int,
    nv_op: int,
    nv_op_name: str | None,
    nv_param: int,
) -> str:
    if prefix is None:
        prefix = ""
    op_name = "" if nv_op_name is None else f"/* {nv_op_name} */"

    return f"{prefix}p = pb_push1_to({nv_channel} /* 0x{nv_class:X} */, p, 0x{nv_op:X} {op_name}, 0x{nv_param:X});"


def push1f_to_pbkit(
    prefix: str | None,
    nv_channel: int,
    nv_class: int,
    nv_op: int,
    nv_op_name: str | None,
    nv_param: int,
) -> str:
    if prefix is None:
        prefix = ""
    op_name = "" if nv_op_name is None else f"/* {nv_op_name} */"

    return f"{prefix}p = pb_push1f_to({nv_channel} /* 0x{nv_class:X} */, p, 0x{nv_op:X} {op_name}, {nv_param});"


def push_to_pbkitplusplus(
    prefix: str | None,
    nv_channel: int,
    nv_class: int,
    nv_op: int,
    nv_op_name: str | None,
    nv_param: int,
    descr: str | None = None,
) -> str:
    if prefix is None:
        prefix = ""
    op_name = "" if nv_op_name is None else f"/* {nv_op_name} */"
    if descr is None:
        descr = ""

    return (
        f"{prefix}Pushbuffer::PushTo({nv_channel} /* 0x{nv_class:X} */, 0x{nv_op:X} {op_name}, 0x{nv_param:X});{descr}"
    )


def pushf_to_pbkitplusplus(
    prefix: str | None,
    nv_channel: int,
    nv_class: int,
    nv_op: int,
    nv_op_name: str | None,
    nv_param: float,
    descr: str | None = None,
) -> str:
    if prefix is None:
        prefix = ""
    op_name = "" if nv_op_name is None else f"/* {nv_op_name} */"
    if descr is None:
        descr = ""

    return f"{prefix}Pushbuffer::PushTo({nv_channel} /* 0x{nv_class:X} */, 0x{nv_op:X} {op_name}, {nv_param});{descr}"


@dataclass
class PGRAPHMethod:
    line_number: int
    draw_number: int

    nv_channel: int
    nv_class: int
    nv_op: int
    nv_param: int

    nv_op_name: str | None = None
    nv_param_float: float | None = None
    nv_param_description: str | None = None

    in_begin_end_block: bool = False

    @property
    def is_beginend_begin(self) -> bool:
        return self.nv_class == 0x97 and self.nv_op == BEGIN_END and self.nv_param != 0

    @property
    def is_beginend_end(self) -> bool:
        return self.nv_class == 0x97 and self.nv_op == BEGIN_END and self.nv_param == 0

    @property
    def is_stateful(self) -> bool:
        # Assume all non-graphics ops are stateful.
        if self.nv_class != 0x97:
            return True

        if self.in_begin_end_block:
            return False

        return self.nv_op not in STATELESS_COMMANDS

    @property
    def is_non_portable(self) -> bool:
        return self.nv_class == 0x97 and self.nv_op in NON_PORTABLE_STATEFUL_COMMANDS

    def to_c(self, *, retain_non_portable: bool = False, pbkitplusplus: bool = False) -> str:
        prefix = "  "
        if self.is_non_portable and not retain_non_portable:
            prefix += "// NONPORTABLE: "

        if self.nv_class == 0x97:
            push = push1_pbkit if not pbkitplusplus else push_pbkitplusplus
            pushf = push1f_pbkit if not pbkitplusplus else pushf_pbkitplusplus
            if self.nv_op_name:
                if self.nv_param_float is None:
                    descr = f"  // {self.nv_param_description}" if self.nv_param_description else ""
                    return push(
                        prefix,
                        self.nv_op,
                        self.nv_op_name,
                        self.nv_param,
                        descr,
                    )

                return pushf(
                    prefix,
                    self.nv_op,
                    self.nv_op_name,
                    self.nv_param_float,
                )

            return push("//", self.nv_op, None, self.nv_param)

        push_to = push1_to_pbkit if not pbkitplusplus else push_to_pbkitplusplus
        if self.nv_op_name:
            pushf_to = push1f_to_pbkit if not pbkitplusplus else pushf_to_pbkitplusplus

            if self.nv_param_float is None:
                return push_to(
                    prefix,
                    self.nv_channel,
                    self.nv_class,
                    self.nv_op,
                    self.nv_op_name,
                    self.nv_param,
                )
            return pushf_to(
                prefix,
                self.nv_channel,
                self.nv_class,
                self.nv_op,
                self.nv_op_name,
                self.nv_param_float,
            )

        return push_to(prefix, self.nv_channel, self.nv_class, self.nv_op, None, self.nv_param)


class PGRAPHComment(PGRAPHMethod):
    def __init__(self, message: str):
        self.message = message

    def to_c(self, *, retain_non_portable: bool = False, pbkitplusplus: bool = False) -> str:
        del retain_non_portable
        del pbkitplusplus
        return f"  // {self.message}"


def _process_pretty_param(param: str) -> tuple[int, str, float | None]:
    match = _PRETTY_ARGUMENT_FLOAT_RE.match(param)
    if match:
        return int(match.group(1), 16), "", float(match.group(2))

    match = PRETTY_ARGUMENT_BITVECTOR_RE.match(param)
    if match:
        return int(match.group(2), 16), match.group(1), None

    match = _PRETTY_ARGUMENT_NAMED_VALUE_RE.match(param)
    if match:
        return int(match.group(2), 16), match.group(1), None

    match = _PRETTY_ARGUMENT_HEX_VALUE_RE.match(param)
    if match:
        return int(match.group(1), 16), "", None

    match = _PRETTY_ARGUMENT_RAW_VALUE_RE.match(param)
    if match:
        return int(match.group(1), 16), "", None

    msg = f"Failed to process pretty param '{param}'"
    raise NotImplementedError(msg)


def _process_file(filename: str) -> list[PGRAPHMethod]:
    draw_number = 1
    in_begin_end = False
    pgraph_methods = []

    with open(filename) as f:
        for line_number, raw_line in enumerate(f):
            line = raw_line.rstrip()

            method: PGRAPHMethod | None = None

            match = _PGRAPH_METHOD_RE.match(line)
            if match:
                method = PGRAPHMethod(
                    line_number=line_number + 1,
                    draw_number=draw_number,
                    nv_channel=int(match.group(1), 0),
                    nv_class=int(match.group(2), 16),
                    nv_op=int(match.group(3), 16),
                    nv_op_name=match.group(4),
                    nv_param=int(match.group(5), 16),
                    in_begin_end_block=in_begin_end,
                )

            if not match:
                match = _PRETTY_PGRAPH_METHOD_RE.match(line)
                if match:
                    param, param_description, float_val = _process_pretty_param(match.group(5))
                    method = PGRAPHMethod(
                        line_number=line_number + 1,
                        draw_number=draw_number,
                        nv_channel=int(match.group(1), 0),
                        nv_class=int(match.group(2), 16),
                        nv_op=int(match.group(4), 16),
                        nv_op_name=match.group(3),
                        nv_param=param,
                        nv_param_float=float_val,
                        nv_param_description=param_description,
                        in_begin_end_block=in_begin_end,
                    )

            if not match:
                match = _UNHANDLED_METHOD_RE.match(line)
                if match:
                    method = PGRAPHMethod(
                        line_number=line_number + 1,
                        draw_number=draw_number,
                        nv_channel=int(match.group(1), 0),
                        nv_class=int(match.group(2), 16),
                        nv_op=int(match.group(3), 16),
                        nv_param=int(match.group(4), 16),
                        in_begin_end_block=in_begin_end,
                    )

            if method:
                if method.is_beginend_begin:
                    in_begin_end = True

                if method.is_beginend_end:
                    in_begin_end = False
                    draw_number += 1

                pgraph_methods.append(method)

    return pgraph_methods


def _first_command_at_or_after(line_num: int, commands: list[PGRAPHMethod]) -> int | None:
    for index, command in enumerate(commands):
        if command.line_number >= line_num:
            return index
    return None


def _filter_draws(commands: list[PGRAPHMethod], start_draw: int, max_draws: int) -> list[PGRAPHMethod]:
    end_draw = start_draw + max_draws

    stateful_commands = {}

    retained_commands = []

    for command in commands:
        if command.draw_number < start_draw:
            if command.is_stateful:
                stateful_commands[command.nv_op] = command
            continue

        if command.draw_number >= end_draw:
            break

        retained_commands.append(command)

    state_commands = sorted(stateful_commands.values(), key=lambda cmd: cmd.line_number)

    # Add a nop tagging the end of the state prefix.
    state_commands.append(PGRAPHComment("END OF SETUP COMMANDS"))

    return state_commands + retained_commands


def _emit_commands(commands: list[PGRAPHMethod], *, retain_non_portable: bool, pbkitplusplus: bool = False):
    processed_since_last_flush = 0

    if not pbkitplusplus:
        print("  uint32_t *p;")
        print("  p = pb_begin();")
    else:
        print("  Pushbuffer::Begin();")

    for command in commands:
        print(command.to_c(retain_non_portable=retain_non_portable, pbkitplusplus=pbkitplusplus))

        if not pbkitplusplus:
            processed_since_last_flush += 1
            if processed_since_last_flush > MAX_COMMANDS_PER_FLUSH:
                print("  pb_end(p);")
                print("  while (pb_busy()) {}")
                print("  p = pb_begin();")
                processed_since_last_flush = 0

    if not pbkitplusplus:
        print("  pb_end(p);")
    else:
        print("  Pushbuffer::End();")


def _main(args):
    filename = os.path.realpath(os.path.expanduser(args.log_file))

    if args.draw:
        args.start_draw = args.draw
        args.max_draws = 1

    def run():
        commands = _process_file(filename)

        if args.list:
            for command_index, command in enumerate(commands):
                if command.is_beginend_end:
                    print(f"Command {command_index} on line {command.line_number} ends draw {command.draw_number}")
            return 0

        if args.start_draw:
            commands = _filter_draws(commands, args.start_draw, args.max_draws)
            _emit_commands(commands, retain_non_portable=args.retain_non_portable)
            return 0

        if args.start_line:
            start_index = _first_command_at_or_after(args.start_line, commands)
            if start_index is None:
                msg = f"No commands at or after {args.start_line}"
                raise ValueError(msg)

            commands = commands[start_index:]

        if args.max_commands:
            commands = commands[: args.max_commands]

        _emit_commands(commands, retain_non_portable=args.retain_non_portable, pbkitplusplus=args.pbkitplusplus)

        return 0

    if not args.out:
        return run()

    output = os.path.realpath(os.path.expanduser(args.out))
    with open(output, "w") as out_file, redirect_stdout(out_file):
        return run()


if __name__ == "__main__":

    def _parse_args():
        parser = argparse.ArgumentParser()

        parser.add_argument(
            "log_file",
            type=str,
            help="The path to the nv2a log to be converted.",
        )

        parser.add_argument(
            "-o",
            "--out",
            metavar="path",
            type=str,
            help="The path at which the converted pbkit commands should be written.",
        )

        parser.add_argument(
            "--start_line",
            metavar="line_num",
            type=int,
            default=0,
            help="The line in the log at which to start processing.",
        )

        parser.add_argument(
            "--max_commands",
            metavar="commands",
            type=int,
            default=0,
            help="The maximum number of nv2a commands to process.",
        )

        parser.add_argument(
            "--start_draw",
            metavar="draw_num",
            type=int,
            default=0,
            help="The draw call in the log at which to start processing.",
        )

        parser.add_argument(
            "--max_draws",
            type=int,
            default=0,
            help="The maximum number of draw calls to process.",
        )

        parser.add_argument(
            "--draw",
            metavar="draw_num",
            type=int,
            help="A single draw call to process (equivalent to '--start_draw <draw_num> --max_draws 1').",
        )

        parser.add_argument(
            "--retain_non_portable",
            action="store_true",
            help="Preserve commands that likely target application-specific memory.",
        )

        parser.add_argument(
            "--list", "-l", action="store_true", help="Print info on draw calls and their ending line numbers"
        )

        parser.add_argument(
            "--pbkitplusplus",
            "-P",
            action="store_true",
            help="Emit PBKitPlusPlus commands rather than raw pbkit",
        )

        return parser.parse_args()

    sys.exit(_main(_parse_args()))
