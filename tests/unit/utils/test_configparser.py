# -*- coding: utf-8 -*-
'''
tests.unit.utils.test_configparser
==================================

Test the funcs in the custom parsers in salt.utils.configparser
'''
# Import Python Libs
from __future__ import absolute_import
import copy
import errno
import logging
import os

log = logging.getLogger(__name__)

# Import Salt Testing Libs
from tests.support.unit import TestCase
from tests.support.paths import TMP

# Import salt libs
import salt.utils.files
import salt.utils.stringutils
import salt.utils.configparser

# The user.name param here is intentionally indented with spaces instead of a
# tab to test that we properly load a file with mixed indentation.
ORIG_CONFIG = u'''[user]
        name = Артём Анисимов
\temail = foo@bar.com
[remote "origin"]
\turl = https://github.com/terminalmage/salt.git
\tfetch = +refs/heads/*:refs/remotes/origin/*
\tpushurl = git@github.com:terminalmage/salt.git
[color "diff"]
\told = 196
\tnew = 39
[core]
\tpager = less -R
\trepositoryformatversion = 0
\tfilemode = true
\tbare = false
\tlogallrefupdates = true
[alias]
\tmodified = ! git status --porcelain | awk 'match($1, "M"){print $2}'
\tgraph = log --all --decorate --oneline --graph
\thist = log --pretty=format:\\"%h %ad | %s%d [%an]\\" --graph --date=short
[http]
\tsslverify = false'''.split(u'\n')  # future lint: disable=non-unicode-string


class TestGitConfigParser(TestCase):
    '''
    Tests for salt.utils.configparser.GitConfigParser
    '''
    maxDiff = None
    orig_config = os.path.join(TMP, u'test_gitconfig.orig')
    new_config = os.path.join(TMP, u'test_gitconfig.new')
    remote = u'remote "origin"'

    def tearDown(self):
        del self.conf
        try:
            os.remove(self.new_config)
        except OSError as exc:
            if exc.errno != errno.ENOENT:
                raise

    def setUp(self):
        if not os.path.exists(self.orig_config):
            with salt.utils.files.fopen(self.orig_config, u'wb') as fp_:
                fp_.write(
                    salt.utils.stringutils.to_bytes(
                        u'\n'.join(ORIG_CONFIG)
                    )
                )
        self.conf = salt.utils.configparser.GitConfigParser()
        self.conf.read(self.orig_config)

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls.orig_config)
        except OSError as exc:
            if exc.errno != errno.ENOENT:
                raise

    @staticmethod
    def fix_indent(lines):
        '''
        Fixes the space-indented 'user' line, because when we write the config
        object to a file space indentation will be replaced by tab indentation.
        '''
        ret = copy.copy(lines)
        for i, _ in enumerate(ret):
            if ret[i].startswith(salt.utils.configparser.GitConfigParser.SPACEINDENT):
                ret[i] = ret[i].replace(salt.utils.configparser.GitConfigParser.SPACEINDENT, u'\t')
        return ret

    @staticmethod
    def get_lines(path):
        with salt.utils.files.fopen(path, u'r') as fp_:
            return salt.utils.stringutils.to_unicode(fp_.read()).splitlines()

    def _test_write(self, mode):
        with salt.utils.files.fopen(self.new_config, mode) as fp_:
            self.conf.write(fp_)
        self.assertEqual(
            self.get_lines(self.new_config),
            self.fix_indent(ORIG_CONFIG)
        )

    def test_get(self):
        '''
        Test getting an option's value
        '''
        # Numeric values should be loaded as strings
        self.assertEqual(self.conf.get(u'color "diff"', u'old'), u'196')
        # Complex strings should be loaded with their literal quotes and
        # slashes intact
        self.assertEqual(
            self.conf.get(u'alias', u'modified'),
            u"""! git status --porcelain | awk 'match($1, "M"){print $2}'"""
        )
        self.assertEqual(
            self.conf.get(u'alias', u'hist'),
            salt.utils.stringutils.to_unicode(
                r"""log --pretty=format:\"%h %ad | %s%d [%an]\" --graph --date=short"""
            )
        )

    def test_read_space_indent(self):
        '''
        Test that user.name was successfully loaded despite being indented
        using spaces instead of a tab. Additionally, this tests that the value
        was loaded as a unicode type on PY2.
        '''
        self.assertEqual(self.conf.get(u'user', u'name'), u'Артём Анисимов')

    def test_set_new_option(self):
        '''
        Test setting a new option in an existing section
        '''
        self.conf.set(u'http', u'useragent', u'myawesomeagent')
        self.assertEqual(self.conf.get(u'http', u'useragent'), u'myawesomeagent')

    def test_add_section(self):
        '''
        Test adding a section and adding an item to that section
        '''
        self.conf.add_section(u'foo')
        self.conf.set(u'foo', u'bar', u'baz')
        self.assertEqual(self.conf.get(u'foo', u'bar'), u'baz')

    def test_replace_option(self):
        '''
        Test replacing an existing option
        '''
        # We're also testing the normalization of key names, here. Setting
        # "sslVerify" should actually set an "sslverify" option.
        self.conf.set(u'http', u'sslVerify', u'true')
        self.assertEqual(self.conf.get(u'http', u'sslverify'), u'true')

    def test_set_multivar(self):
        '''
        Test setting a multivar and then writing the resulting file
        '''
        orig_refspec = u'+refs/heads/*:refs/remotes/origin/*'
        new_refspec = u'+refs/tags/*:refs/tags/*'
        # Make sure that the original value is a string
        self.assertEqual(
            self.conf.get(self.remote, u'fetch'),
            orig_refspec
        )
        # Add another refspec
        self.conf.set_multivar(self.remote, u'fetch', new_refspec)
        # The value should now be a list
        self.assertEqual(
            self.conf.get(self.remote, u'fetch'),
            [orig_refspec, new_refspec]
        )
        # Write the config object to a file
        with salt.utils.files.fopen(self.new_config, 'w') as fp_:
            self.conf.write(fp_)
        # Confirm that the new file was written correctly
        expected = self.fix_indent(ORIG_CONFIG)
        expected.insert(6, u'\tfetch = %s' % new_refspec)  # pylint: disable=string-substitution-usage-error
        self.assertEqual(self.get_lines(self.new_config), expected)

    def test_remove_option(self):
        '''
        test removing an option, including all items from a multivar
        '''
        for item in (u'fetch', u'pushurl'):
            self.conf.remove_option(self.remote, item)
            # To confirm that the option is now gone, a get should raise an
            # NoOptionError exception.
            self.assertRaises(
                salt.utils.configparser.NoOptionError,
                self.conf.get,
                self.remote,
                item)

    def test_remove_option_regexp(self):
        '''
        test removing an option, including all items from a multivar
        '''
        orig_refspec = u'+refs/heads/*:refs/remotes/origin/*'
        new_refspec_1 = u'+refs/tags/*:refs/tags/*'
        new_refspec_2 = u'+refs/foo/*:refs/foo/*'
        # First, add both refspecs
        self.conf.set_multivar(self.remote, u'fetch', new_refspec_1)
        self.conf.set_multivar(self.remote, u'fetch', new_refspec_2)
        # Make sure that all three values are there
        self.assertEqual(
            self.conf.get(self.remote, u'fetch'),
            [orig_refspec, new_refspec_1, new_refspec_2]
        )
        # If the regex doesn't match, no items should be removed
        self.assertFalse(
            self.conf.remove_option_regexp(
                self.remote,
                u'fetch',
                salt.utils.stringutils.to_unicode(r'\d{7,10}')  # future lint: disable=non-unicode-string
            )
        )
        # Make sure that all three values are still there (since none should
        # have been removed)
        self.assertEqual(
            self.conf.get(self.remote, u'fetch'),
            [orig_refspec, new_refspec_1, new_refspec_2]
        )
        # Remove one of the values
        self.assertTrue(
            self.conf.remove_option_regexp(self.remote, u'fetch', u'tags'))
        # Confirm that the value is gone
        self.assertEqual(
            self.conf.get(self.remote, u'fetch'),
            [orig_refspec, new_refspec_2]
        )
        # Remove the other one we added earlier
        self.assertTrue(
            self.conf.remove_option_regexp(self.remote, u'fetch', u'foo'))
        # Since the option now only has one value, it should be a string
        self.assertEqual(self.conf.get(self.remote, u'fetch'), orig_refspec)
        # Remove the last remaining option
        self.assertTrue(
            self.conf.remove_option_regexp(self.remote, u'fetch', u'heads'))
        # Trying to do a get now should raise an exception
        self.assertRaises(
            salt.utils.configparser.NoOptionError,
            self.conf.get,
            self.remote,
            u'fetch')

    def test_write(self):
        '''
        Test writing using non-binary filehandle
        '''
        self._test_write(mode='w')

    def test_write_binary(self):
        '''
        Test writing using binary filehandle
        '''
        self._test_write(mode='wb')
