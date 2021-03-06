"""Main."""

import sys
import csv
import collections
import itertools
import argparse

import yaml

import csv2sql.meta as meta
import csv2sql.queryengines.postgresql
from csv2sql.core.my_logging import get_logger
from csv2sql.core.prefetching import RewindableFileIterator
from csv2sql.core.type_inference import interpret_patterns
from csv2sql.core.type_inference import decide_types


csv.field_size_limit = 1 * 1024 * 1024 * 1024  # 1 Gigabytes.

# Enable PyYAML to treat OrderedDict.
yaml.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    lambda loader, node: collections.OrderedDict(loader.construct_pairs(node))
)
yaml.add_representer(
    collections.OrderedDict,
    lambda dumper, instance: dumper.represent_mapping(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, instance.items())
)


def _decide_patterns(args):
    if hasattr(args, 'pattern_file') and args.pattern_file:
        pattern_file_path = args.pattern_file
        get_logger().info(
            'The pattern file %s will be used.', pattern_file_path)
        with open(pattern_file_path) as pattern_file:
            return yaml.load(pattern_file)
    return args.query_engine.type_patterns()


def _dump_patterns(args):
    patterns = _decide_patterns(args)
    yaml.dump(patterns, args.out_file)


def _dump_schema(args, in_file=None):
    if not in_file:
        in_file = args.in_file

    # Read the header and decide column names.
    reader = csv.reader(in_file, delimiter=args.delimiter)
    column_names = next(reader)
    get_logger().info('Column names are identified: %s', str(column_names))

    num_lines_for_inference = args.lines_for_inference
    if num_lines_for_inference > 0:
        get_logger().info(
            '%d records will be used for type inference.',
            num_lines_for_inference)
        reader = itertools.islice(reader, num_lines_for_inference)

    patterns = _decide_patterns(args)
    type_names = decide_types(
        interpret_patterns(patterns), reader, column_names)
    get_logger().info('Column types are decided: %s', str(type_names))

    args.query_engine.write_schema_statement(
        args.out_file,
        args.table_name,
        zip(column_names, type_names),
        args.rebuild,
    )


def _dump_data(args, in_file=None):
    if not in_file:
        in_file = args.in_file

    # Skip the header.
    reader = csv.reader(in_file, delimiter=args.delimiter)
    next(reader)

    args.query_engine.write_insert_statement(
        args.out_file,
        args.table_name,
        reader,
        args.null,
    )


def _dump_all(args):
    with RewindableFileIterator(args.in_file) as file_iterator:
        _dump_schema(args, in_file=file_iterator)
        file_iterator.rewind()
        frozen_file_iterator = file_iterator.freeze()
        _dump_data(args, in_file=frozen_file_iterator)


def parse_args(arguments):
    """Take a list of commandline arguments and return the parsed arguments."""
    # readable.
    readable = argparse.ArgumentParser(add_help=False)
    readable.add_argument(
        '-i', '--in-file', metavar='PATH',
        help='Input file. [default: std-in]',
        type=argparse.FileType('r'), default=sys.stdin)

    # writable.
    writable = argparse.ArgumentParser(add_help=False)
    writable.add_argument(
        '-o', '--out-file', metavar='PATH',
        help='Output file. [default: std-out]',
        type=argparse.FileType('w'), default=sys.stdout)

    # csv readable.
    csv_readable = argparse.ArgumentParser(add_help=False)
    csv_readable.add_argument(
        '-d', '--delimiter', metavar='STR',
        help='Input delimiter. [default: ,]',
        default=',')
    csv_readable.add_argument(
        '-n', '--null', metavar='STR',
        help='Null string. [default: empty]',
        default='')

    # query_factory.
    query_factory = argparse.ArgumentParser(add_help=False)
    query_factory.add_argument('table_name', help='Table name.')

    # schema_factory.
    schema_factory = argparse.ArgumentParser(add_help=False)
    schema_factory.add_argument(
        '-r', '--rebuild', action='store_true',
        help='Rebuild the table by "DROP TABLE IF EXISTS".')
    schema_factory.add_argument(
        '--lines-for-inference', metavar='NUM',
        help=('Num lines to identify column types.'
              ' When 0, all over the input file will be'
              ' used to identify them. [default: 0]'),
        type=int, default=0)

    # pattern_readable.
    pattern_readable = argparse.ArgumentParser(add_help=False)
    pattern_readable.add_argument(
        '-p', '--pattern-file', metavar='PATH',
        help='Type inference pattern file.')

    # Composed interfaces.
    schema_dumper = [
        readable, writable, csv_readable,
        query_factory, schema_factory, pattern_readable]
    query_dumper = [readable, writable, csv_readable, query_factory]
    pattern_dumper = [writable, pattern_readable]

    # Main.
    parser = argparse.ArgumentParser(
        description='Convert CSV data into an SQL dump.')
    parser.add_argument(
        '-v', '--version', action='version',
        version='%(prog)s {0}'.format(meta.__version__))

    subparsers = parser.add_subparsers(
        title='target', description='What to dump.')
    subparsers.add_parser(
        'all', help='All queries.', parents=schema_dumper,
    ).set_defaults(command=_dump_all)
    subparsers.add_parser(
        'schema', help='Schema queries.', parents=schema_dumper,
    ).set_defaults(command=_dump_schema)
    subparsers.add_parser(
        'data', help='Data-insertion queries.', parents=query_dumper,
    ).set_defaults(command=_dump_data)
    subparsers.add_parser(
        'pattern', help='Type-inference patterns.', parents=pattern_dumper,
    ).set_defaults(command=_dump_patterns)

    args = parser.parse_args(arguments)
    args.query_engine = csv2sql.queryengines.postgresql

    return args


def main():
    """Main."""
    args = parse_args(sys.argv[1:])
    args.command(args)
