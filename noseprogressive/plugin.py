from curses import tigetnum, tigetstr, setupterm, tparm, termname
import inspect
import logging
import os
import sys
from time import sleep
from traceback import format_exception
import unittest
from unittest import TestCase, _WritelnDecorator

from nose.plugins import Plugin
from nose.exc import SkipTest
from nose.case import FunctionTestCase
from nose.util import test_address

log = logging.getLogger('nose.plugins.ProgressivePlugin')


class ProgressivePlugin(Plugin):
    """Nose plugin which prioritizes the important information"""
    name = 'progressive'
    testsRun = 0

    def options(self, parser, env=os.environ):
        super(ProgressivePlugin, self).options(parser, env=env)
        self.parser = parser

    def configure(self, options, conf):
        super(ProgressivePlugin, self).configure(options, conf)
        if self.enabled:
            self.cmd_options = options
            self.config = conf

    def setOutputStream(self, stream):
        """Steal the stream, and return a mock one for everybody else to shut them up."""
        class DevNullStream(object):
            writeln = flush = write = lambda self, *args: None

        self.stream = stream
        
        # Monkeypath sys.stderr to keep other users of the stream (like
        # logging, when you don't pass --logging-clear-handlers) from smearing bits of our progress bar upward:
#         class StreamWrapper(object):
#             def __init__(self, stream):
#                 self._stream = stream
# 
#             def __getattr__(self, name):
#                 return getattr(self._stream, name)
# 
#             def write(self, data):
#                 self._stream.write(data)
#                 self._stream.flush()
#         
#         # TODO: Only if isatty. Consider doing stdout as well.
#         sys.stderr = StreamWrapper(sys.stderr)

        setupterm(None, stream.fileno())  # Make setupterm() work even when -s is passed. TODO: Don't do this if self.stream isn't a terminal. Use os.isatty(self.stream.fileno()). If it isn't, perhaps replace the ShyProgressBar with a dummy object.
        self._bar = ProgressBar()
        return DevNullStream()

    def getDescription(self, test):
        return nice_test_address(test)

    def printError(self, kind, err, test):
        formatted_err = format_exception(*err)
        with ShyProgressBar(self.stream, self._bar):
            writeln = self.stream.writeln
            writeln()
            writeln('=' * 70)
            writeln('%s: %s' % (kind, self.getDescription(test)))
            writeln('-' * 70)
            self.stream.write(''.join(formatted_err))

    def printErrors(self):
        # The current summary doesn't begin with a \n.
        with ShyProgressBar(self.stream, self._bar):
            self.stream.writeln()

    # TODO: Override printSummary() to add footer.
    
    def startTest(self, test):
        self.testsRun += 1
        with AtProgressBar(self.stream):
            self.stream.write(self._bar.get(test, self.testsRun))

    def addError(self, test, err):
        exc, val, tb = err
        with ShyProgressBar(self.stream, self._bar):
            if isinstance(exc, SkipTest):
                self.stream.writeln()
                self.stream.writeln('SKIP: %s' % nice_test_address(test))
            else:
                self.printError('ERROR', err, test)

    def addFailure(self, test, err):
        self.printError('FAIL', err, test)

    def addSkip(self, test, reason):
        # Only in 2.7+
        with ShyProgressBar(self.stream, self._bar):
            self.stream.writeln()
            self.stream.writeln('SKIP: %s' % nice_test_address(test))


class ProgressBar(object):
    def __init__(self):
        width = tigetnum('cols')
        self.last = ' ' * width

    def get(self, test, number):
        number = str(number)
        BOLD = tigetstr('bold')
        test_path = get_context(test.test) + '.' + test.test._testMethodName
        width = tigetnum('cols')
        cols_for_path = width - len(number) - 2  # 2 spaces between path and number
        if len(test_path) > cols_for_path:
            test_path = test_path[len(test_path) - cols_for_path:]
        else:
            test_path += ' ' * (cols_for_path - len(test_path))
        self.last = BOLD + test_path + '  ' + number + BOLD
        return self.last


class AtProgressBar(object):
    """Context manager which goes to the progress bar line on entry and goes back to where it was on exit"""
    
    def __init__(self, stream):
        self.stream = stream

    def __enter__(self):
        """Save position and move to progress bar, col 1."""
        self.stream.write(tigetstr('sc'))  # save position
        height = tigetnum('lines')
        self.stream.write(tparm(tigetstr('cup'), height, 0))
    
    def __exit__(self, type, value, tb):
        self.stream.write(tigetstr('rc'))  # restore position


class ShyProgressBar(object):
    """Context manager that implements a progress bar that gets out of the way"""

    def __init__(self, stream, bar):
        self.stream = stream
        self.bar = bar

    def __enter__(self):
        """Erase the progress bar so bits of disembodied progress bar don't get scrolled up the terminal."""
        # My terminal has no status line, so we make one manually.
        # Doing this each time gives us a hope of adjusting if people resize their terminals during test runs:
        with AtProgressBar(self.stream):
            self.stream.write(tigetstr('el'))  # erase to EOL
        self.stream.flush()

    def __exit__(self, type, value, tb):
        """Do nothing; the bar will come back at the top of the next test, which is imminent."""
        with AtProgressBar(self.stream):
            self.stream.write(self.bar.last)
        self.stream.flush()


def nice_test_address(test):
    addr = test_address(test)
    if addr is None:
        return '??'
    path, module, test_path = addr
    path = nice_path(path)
    if test_path is None:
        return path
    return '%s:%s' % (path, test_path)

nice_test_address.__test__ = False # Not a test for Nose


def get_context(test):
    # TODO: Can't we just use test.address()?
    if isinstance(test, FunctionTestCase):
        context = nice_path(inspect.getfile(inspect.getmodule(test.test)))
    elif isinstance(test, TestCase):
        context = '%s:%s' % (nice_path(inspect.getfile(test.__class__)),
                             test.__class__.__name__)
    else:
        raise NotImplemented('Unsure how to get context from: %r' % test)

    return context


def nice_path(path):
    path = os.path.abspath(path)
    if path.startswith(os.getcwd()):
        path = path.replace(os.getcwd(), '')[1:] # shorten and remove slash
    if path.endswith('.pyc'):
        path = path[0:-1]
    return path