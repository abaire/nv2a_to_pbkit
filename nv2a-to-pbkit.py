#!/usr/bin/env python3

from contextlib import redirect_stdout
import argparse
import os
import re
import sys

# Maximum number of pgraph commands per pb_begin/end block
MAX_COMMANDS_PER_FLUSH = 64

_HEX_VALUE = r"0x[0-9a-fA-F]+"
# fmt: off
_PGRAPH_METHOD_RE = re.compile(
    r"nv2a: pgraph method \((\d+)\):\s+(" + _HEX_VALUE + r") -> (" + _HEX_VALUE + r")\s+(?:(\S+)\s+)?\((" + _HEX_VALUE + r")\)"
)
_UNHANDLED_METHOD_RE = re.compile(
    r"nv2a:\s+unhandled\s+\((" + _HEX_VALUE + r")\s+(" + _HEX_VALUE + r")\)"
)
# fmt: on


def _convert_pgraph_method(_channel, nv_class, nv_op, nv_op_name, nv_param):
    if nv_class == 0x97:
        print("  p = pb_push1(p, 0x%X /*%s*/, 0x%X);" % (nv_op, nv_op_name, nv_param))
        return

    print(
        "  // p = pb_pushX_to_0x%X(p, 0x%X /*%s*/, 0x%X);"
        % (nv_class, nv_op, nv_op_name, nv_param)
    )


def _convert_unhandled_method(nv_class, nv_op):
    if nv_class == 0x97:
        print(
            "  // p = pb_pushX(p, 0x%X, /* TODO: extend unhandled method log to include param */);"
            % nv_op
        )
        return

    print(
        "  // p = pb_pushX_to_0x%X(p, 0x%X, /* TODO: extend unhandled method log to include param */);"
        % (nv_class, nv_op)
    )


def _process_file(filename, start_line, max_lines):
    line_number = 1
    processed_lines = 0
    processed_since_last_flush = 0

    print("  uint32_t *p;")
    print("  p = pb_begin();")

    with open(filename, "r") as f:
        for line in f:
            if line_number < start_line:
                continue

            if max_lines and processed_lines >= max_lines:
                print("  // --max_lines exceeded")
                break

            if processed_since_last_flush > MAX_COMMANDS_PER_FLUSH:
                print("  pb_end(p);")
                print("  while (pb_busy()) {}")
                print("  p = pb_begin();")
                processed_since_last_flush = 0

            line = line.rstrip()
            match = _PGRAPH_METHOD_RE.match(line)
            if match:
                _convert_pgraph_method(
                    int(match.group(1), 0),
                    int(match.group(2), 16),
                    int(match.group(3), 16),
                    match.group(4),
                    int(match.group(5), 16),
                )

                processed_lines += 1
                processed_since_last_flush += 1
                continue

            match = _UNHANDLED_METHOD_RE.match(line)
            if match:
                _convert_unhandled_method(
                    int(match.group(1), 16), int(match.group(2), 16)
                )
                processed_lines += 1
                processed_since_last_flush += 1
                continue

    print("  pb_end(p);")


def _main(args):

    filename = os.path.realpath(os.path.expanduser(args.log_file))

    if not args.out:
        _process_file(filename, args.start_line, args.max_lines)
        return 0

    output = os.path.realpath(os.path.expanduser(args.out))
    output = os.path.realpath(os.path.expanduser(output))
    with open(output, "w") as out_file:
        with redirect_stdout(out_file):
            _process_file(filename, args.start_line, args.max_lines)
    return 0


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
            "-s",
            "--start_line",
            metavar="line_num",
            type=int,
            default=0,
            help="The line in the log at which to start processing.",
        )

        parser.add_argument(
            "--max_lines",
            metavar="lines",
            type=int,
            default=0,
            help="The maximum number of nv2a commands to process.",
        )

        return parser.parse_args()

    sys.exit(_main(_parse_args()))
