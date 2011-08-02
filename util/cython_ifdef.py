#!/usr/bin/python
# Copyright (C) 2011 Denis Bilenko (http://denisbilenko.com)
# Homepage: http://github.com/denik/cython-ifdef
import sys
import os
import datetime
from cStringIO import StringIO
import difflib
import uuid

# #if XXX require different configuration to process than #ifdef
# while for "#ifdef XXX" it's enough to do "-DXXX" and "-UXXX",
# for "#if XXX", we need "-DXXX=1" and "-DXXX=0".


newline_token = ' %s ' % uuid.uuid4().hex


class options:
    output = None
    verbose = False


def get_symbols(filename):
    command = "unifdef -t -s '%s'" % filename
    popen = os.popen(command)
    result = popen.read().strip().split()
    returncode = popen.close()
    if returncode is not None:
        sys.exit('%r failed with code %r' % (command, os.WEXITSTATUS(returncode)))
    return sorted(set(result))


def parse_commandline():
    argv = sys.argv[1:]
    if not argv:
        sys.exit('Usage: %s [cython-options] sourcefile.pyx' % sys.argv[0])
    sourcefile = options.sourcefile = argv[-1]
    del argv[-1]
    if not os.path.exists(sourcefile):
        sys.exit('File not found: %s' % sourcefile)
    if not sourcefile.endswith('.pyx') and not sourcefile.endswith('.py'):
        sys.exit('Invalid extension: %s' % sourcefile)
    try:
        index = argv.index('-o')
    except ValueError:
        try:
            index = argv.index('--output-file')
        except ValueError:
            path, name = os.path.split(sourcefile)
            name = name.rsplit('.', 1)[0] + '.c'
            options.output = os.path.join(path, name)
    if options.output is None:
        try:
            del argv[index]
            options.output = argv[index]
            del argv[index]
        except IndexError:
            sys.exit('Invalid command line: %s' % (sys.argv, ))
    options.cython_args = ' '.join(argv)


def system(command):
    print command
    result = os.system(command)
    if result:
        sys.exit('%r failed with code %s' % (command, os.WEXITSTATUS(result)))


def system_unifdef(command):
    print command
    result = os.system(command)
    result = os.WEXITSTATUS(result)
    if result not in (0, 1):
        sys.exit('%r failed with code %s' % (command, result))


def unlink(filename):
    try:
        os.unlink(filename)
    except OSError, ex:
        if 'no such file' not in str(ex).lower():
            raise


def link_force(source, dest):
    unlink(dest)
    return os.link(source, dest)


class Config(object):

    def __init__(self, key):
        self.key = key
        label = key.replace(' ', '_').replace('-', '_')
        sourcename = os.path.basename(options.sourcefile)
        base = sourcename.rsplit('.', 1)[0] + label
        self.pyx_name = base + '.pyx'
        self.c_name = base + '.c'

    def __str__(self):
        return self.key


def convert_comments(filename, today):
    output = open(filename + '.temp', 'w')
    input = open(filename)
    firstline = input.readline()

    if firstline.strip().lower().startswith('/* generated by cython ') and firstline.strip().endswith('*/'):
        line = firstline.strip().strip('/*').strip().split(' on ')[0]
        output.write('/* ' + line + ' + cython_ifdef.py on %s */\n' % today)
    else:
        output.write(firstline)

    in_comment = False
    for line in input:
        if in_comment:
            if '*/' in line:
                in_comment = False
                output.write(line)
            else:
                output.write(line.replace('\n', newline_token))
        else:
            if line.lstrip().startswith('/* ') and '*/' not in line:
                line = line.replace('\n', newline_token)
                output.write(line)
                in_comment = True
            else:
                output.write(line)
    output.flush()
    output.close()
    os.rename(filename + '.temp', filename)


def compact_tag_set(tags):
    for tag in tags.copy():
        prefix, symbol = tag[:2], tag[2:]
        reverse = {'-D': '-U', '-U': '-D'}.get(prefix)
        if reverse is None:
            raise ValueError('Cannot process: %r' % (tag, ))
        reverse += symbol
        if reverse in tags:
            tags.discard(tag)
            tags.discard(reverse)


class Str(str):

    def __new__(cls, string, tag=None):
        if tag is None:
            tag = getattr(string, 'tag', set())
        self = str.__new__(cls, string)
        self.string = string
        self.tag = set(tag)
        return self

    def __repr__(self):
        return '%s(%s, %r)' % (self.__class__.__name__, str.__repr__(self), self.tag)

    def __add__(self, other):
        newtag = self.tag | getattr(other, 'tag', set())
        return self.__class__(str.__add__(self, other), newtag)

    def __radd__(self, other):
        newtag = self.tag | getattr(other, 'tag', set())
        return self.__class__(str.__add__(other, self), newtag)

    methods = ['__getslice__', '__getitem__', '__mul__', '__rmod__', '__rmul__',
               'join', 'replace', 'upper', 'lower']

    for method in methods:
        exec '''def %s(self, *args):
    return self.__class__(str.%s(self, *args), self.tag)''' % (method, method)


def unified_diff(a, b, fromfile='', tofile='', fromfiledate='',
                 tofiledate='', n=1000000, lineterm='\n'):
    started = False
    for group in difflib.SequenceMatcher(None, a, b).get_grouped_opcodes(n):
        if not started:
            started = True
        i1, i2, j1, j2 = group[0][1], group[-1][2], group[0][3], group[-1][4]
        for tag, i1, i2, j1, j2 in group:
            if tag == 'equal':
                assert i2 - i1 == j2 - j1, locals()
                for line_a, line_b in zip(a[i1:i2], b[j1:j2]):
                    tag = getattr(line_a, 'tag', set()) | getattr(line_b, 'tag', set())
                    line = Str(line_a, tag)
                    yield ' ' + line
                continue
            if tag == 'replace' or tag == 'delete':
                for line in a[i1:i2]:
                    yield '-' + line
            if tag == 'replace' or tag == 'insert':
                for line in b[j1:j2]:
                    yield '+' + line


def _merge(lines1, lines2, tag1, tag2, tag3):
    tags = {'-': set(tag2),
            '+': set(tag1),
            ' ': set(tag3)}
    for line in unified_diff(lines2, lines1, n=100000):
        x = Str(line[1:])
        x.tag |= tags[line[0]]
        compact_tag_set(x.tag)
        yield x


class Source(object):

    def __init__(self, text, config):
        if isinstance(text, str):
            self.lines = StringIO(text).readlines()
        elif isinstance(text, list):
            self.lines = text
        else:
            raise TypeError('Invalid type: %r' % (text, ))
        self.key = _tags(config)
        self.config = set(self.key.split())
        self.symbols = set(x[2:] for x in self.config)

    def __repr__(self):
        return 'Source(%s lines, %r)' % (len(self.lines), self.key)


def sortkey(option):
    opt, symbol = option[:2], option[2:]
    return symbol, opt


def _tags(config):
    if isinstance(config, str):
        config = config.split()
    config = set(config)
    for x in config:
        if x.startswith('-D') or x.startswith('-U') and len(x) > 2:
            pass
        else:
            raise ValueError('Bad entry %r in config %r' % (x, config))
    return ' '.join(sorted(config, key=sortkey))


def pairs(iterable):
    iterator = iter(iterable)
    while True:
        try:
            a = iterator.next()
        except StopIteration:
            return
        try:
            b = iterator.next()
        except StopIteration:
            raise AssertionError('Invalid argument for pairs: %s' % (iterable, ))
        yield (a, b)


def _bin(number, length):
    result = bin(number)[2:]
    return '0' * (length - len(result)) + result


def iter_configurations(symbols):
    size = len(symbols)
    for x in xrange(2 ** size):
        config = _bin(x, size)
        config = zip(config, symbols)
        config = ['-D' + y if x == '1' else '-U' + y for (x, y) in config]
        yield _tags(config)


def get_configurations(symbols):
    return list(iter_configurations(symbols))


def merge(sources):
    r"""
    >>> src1 = Source('hello\nworld\n', '-Dhello -Dworld')
    >>> src2 = Source('goodbye\nworld\n', '-Uhello -Dworld')
    >>> src3 = Source('hello\neveryone\n', '-Dhello -Uworld')
    >>> src4 = Source('goodbye\neveryone\n', '-Uhello -Uworld')
    >>> from pprint import pprint
    >>> pprint(merge([src1, src2, src3, src4]))
    [('hello\n', '-Dhello'),
     ('goodbye\n', '-Uhello'),
     ('world\n', '-Dworld'),
     ('everyone\n', '-Uworld')]
    """
    symbols = set()
    mapping = {}
    for source in sources:
        symbols.update(source.symbols)
        mapping[source.key] = source
    #print 'MERGE', symbols
    new_sources = []
    for keyD, keyU in pairs(get_configurations(symbols)):
        #print '#', keyD, '#', keyU
        srcD = mapping[keyD]
        srcU = mapping[keyU]
        common = srcD.config & srcU.config
        lines = list(_merge(srcD.lines, srcU.lines, srcD.config, srcU.config, common))
        #sys.stderr.write('.')
        new_sources.append(Source(lines, common))
    if not new_sources:
        raise ValueError("Something went wrong")
    elif len(new_sources) == 1:
        return [(str(x), _tags(x.tag)) for x in new_sources[0].lines]
    return merge(new_sources)


def convert_key_to_ifdef(key):
    tags = key.split()
    result = []
    if len(tags) == 1:
        tag = tags[0]
        if tag.startswith('-D'):
            return '#ifdef %s' % tag[2:]
        elif tag.startswith('-U'):
            return '#ifndef %s' % tag[2:]
    for tag in tags:
        if tag.startswith('-D'):
            result.append('defined (%s)' % tag[2:])
        elif tag.startswith('-U'):
            result.append('!defined (%s)' % tag[2:])
        else:
            raise ValueError(repr(tags))
    return '#if ' + ' && '.join(result)


def exact_reverse(a, b):
    if not a or not b:
        return
    a = a.split()
    b = b.split()
    if len(a) != 1:
        return
    if len(b) != 1:
        return
    a = a[0]
    b = b[0]
    if a[2:] != b[2:]:
        return
    if sorted([a[:2], b[:2]]) == ['-D', '-U']:
        return True


def produce_preprocessor(iterable):
    def wrap(line, log=True):
        current_line[0] += 1
        if options.verbose and log:
            sys.stdout.write('%5d: %s' % (current_line[0], line))
        return line

    state = None
    current_line = [0]
    for line, key in iterable:
        key = key or None
        if key == state:
            yield wrap(line, key)
        else:
            if exact_reverse(key, state):
                yield wrap('#else\n')
            else:
                if state:
                    yield wrap('#endif /* %s */\n' % state)
                if key:
                    yield wrap(convert_key_to_ifdef(key) + '\n')
            yield wrap(line, key)
            state = key
    if state:
        yield '#endif\n'


def main():
    parse_commandline()
    symbols = get_symbols(options.sourcefile)

    if not symbols:
        system('cython %s -o %s %s' % (options.cython_args, options.output, options.sourcefile))
        # TODO: do exec
        sys.exit(0)

    print '%s: found symbols: %s' % (options.sourcefile, ', '.join(symbols))
    today = str(datetime.date.today())
    sources = []

    tmpname = options.sourcefile + '.saved.%s' % os.getpid()
    os.rename(options.sourcefile, tmpname)

    try:
        for key in iter_configurations(symbols):
            system_unifdef('unifdef -t -b %s -o %s %s' % (key, options.sourcefile, tmpname))
            system('cython %s -o %s %s' % (options.cython_args, options.output, options.sourcefile))
            convert_comments(options.output, today)
            sources.append(Source(open(options.output).read(), key))
    finally:
        os.rename(tmpname, options.sourcefile)

    sys.stderr.write('Merging (might take a while)\n')
    write = open(options.output, 'w').write
    for line in produce_preprocessor(merge(sources)):
        write(line.replace(newline_token, '\n'))


if __name__ == '__main__':
    main()
