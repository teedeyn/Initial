"""Tests for distutils.command.sdist."""
import os
import tarfile
import unittest
import warnings
import zipfile
from os.path import join
from textwrap import dedent
from test.support import captured_stdout, run_unittest

from .py38compat import check_warnings

try:
    import zlib
    ZLIB_SUPPORT = True
except ImportError:
    ZLIB_SUPPORT = False

try:
    import grp
    import pwd
    UID_GID_SUPPORT = True
except ImportError:
    UID_GID_SUPPORT = False

from distutils.command.sdist import sdist, show_formats
from distutils.core import Distribution
from distutils.tests.test_config import BasePyPIRCCommandTestCase
from distutils.errors import DistutilsOptionError
from distutils.spawn import find_executable
from distutils.log import WARN
from distutils.filelist import FileList
from distutils.archive_util import ARCHIVE_FORMATS

SETUP_PY = """
from distutils.core import setup
import somecode

setup(name='fake')
"""

MANIFEST = """\
# file GENERATED by distutils, do NOT edit
README
buildout.cfg
inroot.txt
setup.py
data%(sep)sdata.dt
scripts%(sep)sscript.py
some%(sep)sfile.txt
some%(sep)sother_file.txt
somecode%(sep)s__init__.py
somecode%(sep)sdoc.dat
somecode%(sep)sdoc.txt
"""

class SDistTestCase(BasePyPIRCCommandTestCase):

    def setUp(self):
        # PyPIRCCommandTestCase creates a temp dir already
        # and put it in self.tmp_dir
        super(SDistTestCase, self).setUp()
        # setting up an environment
        self.old_path = os.getcwd()
        os.mkdir(join(self.tmp_dir, 'somecode'))
        os.mkdir(join(self.tmp_dir, 'dist'))
        # a package, and a README
        self.write_file((self.tmp_dir, 'README'), 'xxx')
        self.write_file((self.tmp_dir, 'somecode', '__init__.py'), '#')
        self.write_file((self.tmp_dir, 'setup.py'), SETUP_PY)
        os.chdir(self.tmp_dir)

    def tearDown(self):
        # back to normal
        os.chdir(self.old_path)
        super(SDistTestCase, self).tearDown()

    def get_cmd(self, metadata=None):
        """Returns a cmd"""
        if metadata is None:
            metadata = {'name': 'fake', 'version': '1.0',
                        'url': 'xxx', 'author': 'xxx',
                        'author_email': 'xxx'}
        dist = Distribution(metadata)
        dist.script_name = 'setup.py'
        dist.packages = ['somecode']
        dist.include_package_data = True
        cmd = sdist(dist)
        cmd.dist_dir = 'dist'
        return dist, cmd

    @unittest.skipUnless(ZLIB_SUPPORT, 'Need zlib support to run')
    def test_prune_file_list(self):
        # this test creates a project with some VCS dirs and an NFS rename
        # file, then launches sdist to check they get pruned on all systems

        # creating VCS directories with some files in them
        os.mkdir(join(self.tmp_dir, 'somecode', '.svn'))
        self.write_file((self.tmp_dir, 'somecode', '.svn', 'ok.py'), 'xxx')

        os.mkdir(join(self.tmp_dir, 'somecode', '.hg'))
        self.write_file((self.tmp_dir, 'somecode', '.hg',
                         'ok'), 'xxx')

        os.mkdir(join(self.tmp_dir, 'somecode', '.git'))
        self.write_file((self.tmp_dir, 'somecode', '.git',
                         'ok'), 'xxx')

        self.write_file((self.tmp_dir, 'somecode', '.nfs0001'), 'xxx')

        # now building a sdist
        dist, cmd = self.get_cmd()

        # zip is available universally
        # (tar might not be installed under win32)
        cmd.formats = ['zip']

        cmd.ensure_finalized()
        cmd.run()

        # now let's check what we have
        dist_folder = join(self.tmp_dir, 'dist')
        files = os.listdir(dist_folder)
        self.assertEqual(files, ['fake-1.0.zip'])

        zip_file = zipfile.ZipFile(join(dist_folder, 'fake-1.0.zip'))
        try:
            content = zip_file.namelist()
        finally:
            zip_file.close()

        # making sure everything has been pruned correctly
        expected = ['', 'PKG-INFO', 'README', 'setup.py',
                    'somecode/', 'somecode/__init__.py']
        self.assertEqual(sorted(content), ['fake-1.0/' + x for x in expected])

    @unittest.skipUnless(ZLIB_SUPPORT, 'Need zlib support to run')
    @unittest.skipIf(find_executable('tar') is None,
                     "The tar command is not found")
    @unittest.skipIf(find_executable('gzip') is None,
                     "The gzip command is not found")
    def test_make_distribution(self):
        # now building a sdist
        dist, cmd = self.get_cmd()

        # creating a gztar then a tar
        cmd.formats = ['gztar', 'tar']
        cmd.ensure_finalized()
        cmd.run()

        # making sure we have two files
        dist_folder = join(self.tmp_dir, 'dist')
        result = os.listdir(dist_folder)
        result.sort()
        self.assertEqual(result, ['fake-1.0.tar', 'fake-1.0.tar.gz'])

        os.remove(join(dist_folder, 'fake-1.0.tar'))
        os.remove(join(dist_folder, 'fake-1.0.tar.gz'))

        # now trying a tar then a gztar
        cmd.formats = ['tar', 'gztar']

        cmd.ensure_finalized()
        cmd.run()

        result = os.listdir(dist_folder)
        result.sort()
        self.assertEqual(result, ['fake-1.0.tar', 'fake-1.0.tar.gz'])

    @unittest.skipUnless(ZLIB_SUPPORT, 'Need zlib support to run')
    def test_add_defaults(self):

        # http://bugs.python.org/issue2279

        # add_default should also include
        # data_files and package_data
        dist, cmd = self.get_cmd()

        # filling data_files by pointing files
        # in package_data
        dist.package_data = {'': ['*.cfg', '*.dat'],
                             'somecode': ['*.txt']}
        self.write_file((self.tmp_dir, 'somecode', 'doc.txt'), '#')
        self.write_file((self.tmp_dir, 'somecode', 'doc.dat'), '#')

        # adding some data in data_files
        data_dir = join(self.tmp_dir, 'data')
        os.mkdir(data_dir)
        self.write_file((data_dir, 'data.dt'), '#')
        some_dir = join(self.tmp_dir, 'some')
        os.mkdir(some_dir)
        # make sure VCS directories are pruned (#14004)
        hg_dir = join(self.tmp_dir, '.hg')
        os.mkdir(hg_dir)
        self.write_file((hg_dir, 'last-message.txt'), '#')
        # a buggy regex used to prevent this from working on windows (#6884)
        self.write_file((self.tmp_dir, 'buildout.cfg'), '#')
        self.write_file((self.tmp_dir, 'inroot.txt'), '#')
        self.write_file((some_dir, 'file.txt'), '#')
        self.write_file((some_dir, 'other_file.txt'), '#')

        dist.data_files = [('data', ['data/data.dt',
                                     'buildout.cfg',
                                     'inroot.txt',
                                     'notexisting']),
                           'some/file.txt',
                           'some/other_file.txt']

        # adding a script
        script_dir = join(self.tmp_dir, 'scripts')
        os.mkdir(script_dir)
        self.write_file((script_dir, 'script.py'), '#')
        dist.scripts = [join('scripts', 'script.py')]

        cmd.formats = ['zip']
        cmd.use_defaults = True

        cmd.ensure_finalized()
        cmd.run()

        # now let's check what we have
        dist_folder = join(self.tmp_dir, 'dist')
        files = os.listdir(dist_folder)
        self.assertEqual(files, ['fake-1.0.zip'])

        zip_file = zipfile.ZipFile(join(dist_folder, 'fake-1.0.zip'))
        try:
            content = zip_file.namelist()
        finally:
            zip_file.close()

        # making sure everything was added
        expected = ['', 'PKG-INFO', 'README', 'buildout.cfg',
                    'data/', 'data/data.dt', 'inroot.txt',
                    'scripts/', 'scripts/script.py', 'setup.py',
                    'some/', 'some/file.txt', 'some/other_file.txt',
                    'somecode/', 'somecode/__init__.py', 'somecode/doc.dat',
                    'somecode/doc.txt']
        self.assertEqual(sorted(content), ['fake-1.0/' + x for x in expected])

        # checking the MANIFEST
        f = open(join(self.tmp_dir, 'MANIFEST'))
        try:
            manifest = f.read()
        finally:
            f.close()
        self.assertEqual(manifest, MANIFEST % {'sep': os.sep})

    @unittest.skipUnless(ZLIB_SUPPORT, 'Need zlib support to run')
    def test_metadata_check_option(self):
        # testing the `medata-check` option
        dist, cmd = self.get_cmd(metadata={})

        # this should raise some warnings !
        # with the `check` subcommand
        cmd.ensure_finalized()
        cmd.run()
        warnings = [msg for msg in self.get_logs(WARN) if
                    msg.startswith('warning: check:')]
        self.assertEqual(len(warnings), 2)

        # trying with a complete set of metadata
        self.clear_logs()
        dist, cmd = self.get_cmd()
        cmd.ensure_finalized()
        cmd.metadata_check = 0
        cmd.run()
        warnings = [msg for msg in self.get_logs(WARN) if
                    msg.startswith('warning: check:')]
        self.assertEqual(len(warnings), 0)

    def test_check_metadata_deprecated(self):
        # makes sure make_metadata is deprecated
        dist, cmd = self.get_cmd()
        with check_warnings() as w:
            warnings.simplefilter("always")
            cmd.check_metadata()
            self.assertEqual(len(w.warnings), 1)

    def test_show_formats(self):
        with captured_stdout() as stdout:
            show_formats()

        # the output should be a header line + one line per format
        num_formats = len(ARCHIVE_FORMATS.keys())
        output = [line for line in stdout.getvalue().split('\n')
                  if line.strip().startswith('--formats=')]
        self.assertEqual(len(output), num_formats)

    def test_finalize_options(self):
        dist, cmd = self.get_cmd()
        cmd.finalize_options()

        # default options set by finalize
        self.assertEqual(cmd.manifest, 'MANIFEST')
        self.assertEqual(cmd.template, 'MANIFEST.in')
        self.assertEqual(cmd.dist_dir, 'dist')

        # formats has to be a string splitable on (' ', ',') or
        # a stringlist
        cmd.formats = 1
        self.assertRaises(DistutilsOptionError, cmd.finalize_options)
        cmd.formats = ['zip']
        cmd.finalize_options()

        # formats has to be known
        cmd.formats = 'supazipa'
        self.assertRaises(DistutilsOptionError, cmd.finalize_options)

    # the following tests make sure there is a nice error message instead
    # of a traceback when parsing an invalid manifest template

    def _check_template(self, content):
        dist, cmd = self.get_cmd()
        os.chdir(self.tmp_dir)
        self.write_file('MANIFEST.in', content)
        cmd.ensure_finalized()
        cmd.filelist = FileList()
        cmd.read_template()
        warnings = self.get_logs(WARN)
        self.assertEqual(len(warnings), 1)

    def test_invalid_template_unknown_command(self):
        self._check_template('taunt knights *')

    def test_invalid_template_wrong_arguments(self):
        # this manifest command takes one argument
        self._check_template('prune')

    @unittest.skipIf(os.name != 'nt', 'test relevant for Windows only')
    def test_invalid_template_wrong_path(self):
        # on Windows, trailing slashes are not allowed
        # this used to crash instead of raising a warning: #8286
        self._check_template('include examples/')

    @unittest.skipUnless(ZLIB_SUPPORT, 'Need zlib support to run')
    def test_get_file_list(self):
        # make sure MANIFEST is recalculated
        dist, cmd = self.get_cmd()

        # filling data_files by pointing files in package_data
        dist.package_data = {'somecode': ['*.txt']}
        self.write_file((self.tmp_dir, 'somecode', 'doc.txt'), '#')
        cmd.formats = ['gztar']
        cmd.ensure_finalized()
        cmd.run()

        f = open(cmd.manifest)
        try:
            manifest = [line.strip() for line in f.read().split('\n')
                        if line.strip() != '']
        finally:
            f.close()

        self.assertEqual(len(manifest), 5)

        # adding a file
        self.write_file((self.tmp_dir, 'somecode', 'doc2.txt'), '#')

        # make sure build_py is reinitialized, like a fresh run
        build_py = dist.get_command_obj('build_py')
        build_py.finalized = False
        build_py.ensure_finalized()

        cmd.run()

        f = open(cmd.manifest)
        try:
            manifest2 = [line.strip() for line in f.read().split('\n')
                         if line.strip() != '']
        finally:
            f.close()

        # do we have the new file in MANIFEST ?
        self.assertEqual(len(manifest2), 6)
        self.assertIn('doc2.txt', manifest2[-1])

    @unittest.skipUnless(ZLIB_SUPPORT, 'Need zlib support to run')
    def test_manifest_marker(self):
        # check that autogenerated MANIFESTs have a marker
        dist, cmd = self.get_cmd()
        cmd.ensure_finalized()
        cmd.run()

        f = open(cmd.manifest)
        try:
            manifest = [line.strip() for line in f.read().split('\n')
                        if line.strip() != '']
        finally:
            f.close()

        self.assertEqual(manifest[0],
                         '# file GENERATED by distutils, do NOT edit')

    @unittest.skipUnless(ZLIB_SUPPORT, "Need zlib support to run")
    def test_manifest_comments(self):
        # make sure comments don't cause exceptions or wrong includes
        contents = dedent("""\
            # bad.py
            #bad.py
            good.py
            """)
        dist, cmd = self.get_cmd()
        cmd.ensure_finalized()
        self.write_file((self.tmp_dir, cmd.manifest), contents)
        self.write_file((self.tmp_dir, 'good.py'), '# pick me!')
        self.write_file((self.tmp_dir, 'bad.py'), "# don't pick me!")
        self.write_file((self.tmp_dir, '#bad.py'), "# don't pick me!")
        cmd.run()
        self.assertEqual(cmd.filelist.files, ['good.py'])

    @unittest.skipUnless(ZLIB_SUPPORT, 'Need zlib support to run')
    def test_manual_manifest(self):
        # check that a MANIFEST without a marker is left alone
        dist, cmd = self.get_cmd()
        cmd.formats = ['gztar']
        cmd.ensure_finalized()
        self.write_file((self.tmp_dir, cmd.manifest), 'README.manual')
        self.write_file((self.tmp_dir, 'README.manual'),
                         'This project maintains its MANIFEST file itself.')
        cmd.run()
        self.assertEqual(cmd.filelist.files, ['README.manual'])

        f = open(cmd.manifest)
        try:
            manifest = [line.strip() for line in f.read().split('\n')
                        if line.strip() != '']
        finally:
            f.close()

        self.assertEqual(manifest, ['README.manual'])

        archive_name = join(self.tmp_dir, 'dist', 'fake-1.0.tar.gz')
        archive = tarfile.open(archive_name)
        try:
            filenames = [tarinfo.name for tarinfo in archive]
        finally:
            archive.close()
        self.assertEqual(sorted(filenames), ['fake-1.0', 'fake-1.0/PKG-INFO',
                                             'fake-1.0/README.manual'])

    @unittest.skipUnless(ZLIB_SUPPORT, "requires zlib")
    @unittest.skipUnless(UID_GID_SUPPORT, "Requires grp and pwd support")
    @unittest.skipIf(find_executable('tar') is None,
                     "The tar command is not found")
    @unittest.skipIf(find_executable('gzip') is None,
                     "The gzip command is not found")
    def test_make_distribution_owner_group(self):
        # now building a sdist
        dist, cmd = self.get_cmd()

        # creating a gztar and specifying the owner+group
        cmd.formats = ['gztar']
        cmd.owner = pwd.getpwuid(0)[0]
        cmd.group = grp.getgrgid(0)[0]
        cmd.ensure_finalized()
        cmd.run()

        # making sure we have the good rights
        archive_name = join(self.tmp_dir, 'dist', 'fake-1.0.tar.gz')
        archive = tarfile.open(archive_name)
        try:
            for member in archive.getmembers():
                self.assertEqual(member.uid, 0)
                self.assertEqual(member.gid, 0)
        finally:
            archive.close()

        # building a sdist again
        dist, cmd = self.get_cmd()

        # creating a gztar
        cmd.formats = ['gztar']
        cmd.ensure_finalized()
        cmd.run()

        # making sure we have the good rights
        archive_name = join(self.tmp_dir, 'dist', 'fake-1.0.tar.gz')
        archive = tarfile.open(archive_name)

        # note that we are not testing the group ownership here
        # because, depending on the platforms and the container
        # rights (see #7408)
        try:
            for member in archive.getmembers():
                self.assertEqual(member.uid, os.getuid())
        finally:
            archive.close()

def test_suite():
    return unittest.makeSuite(SDistTestCase)

if __name__ == "__main__":
    run_unittest(test_suite())
