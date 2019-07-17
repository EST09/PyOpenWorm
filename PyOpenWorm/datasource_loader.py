# -*- coding: utf-8 -*-
'''
DataSourceLoaders take a data source identifier and retrieve the primary data (e.g., CSV files, electrode recordings)
from some location (e.g., a file store, via a bittorrent tracker).

Each loader can treat the base_directory given as its own namespace and place directories in there however it wants.
'''
from yarom.utils import FCN
from os.path import exists, isdir, join as pth_join, isabs, realpath
import six


class DataSourceDirLoaderMeta(type):

    # Logic behind this: I want to provide a good default of the FCN, but also allow implementers to say "I just want to
    # use a class variable". You can also subclass this meta, set dirkey in the meta's class definition and then
    # override in instances of that meta by explicitly setting dirkey in the instance...so best of both.
    @property
    def dirkey(self):
        return getattr(self, 'directory_key', None) or FCN(self)


class DataSourceDirLoader(six.with_metaclass(DataSourceDirLoaderMeta, object)):
    '''
    Loads a data files for a DataSource

    The loader is expected to organize files for each data source within the given
    base directory.
    '''
    def __init__(self, base_directory=None):
        if base_directory:
            self.base_directory = realpath(base_directory)

    def __call__(self, data_source):
        '''
        Load the data source

        Parameters
        ----------
        data_source : PyOpenWorm.datasource.DataSource
            The data source to load data for

        Returns
        -------
        A path to the loaded resource

        Raises
        ------
        LoadFailed
        '''
        # Call str(·) to give a more uniform interface to the sub-class ``load``
        # Conventionally, types that tag or "enhance" a string have the base string representation as their __str__
        s = self.load(data_source)
        if not s:
            raise LoadFailed(data_source, self, 'Loader returned an empty string')

        # N.B.: This logic is NOT intended as a security measure against directory traversal: it is only to make the
        # interface both flexible and unambiguous for implementers

        # Relative paths are allowed
        if not isabs(s):
            s = pth_join(self.base_directory, s)

        # Make sure the loader isn't doing some nonsense with symlinks or non-portable paths
        rpath = realpath(s)
        if not rpath.startswith(self.base_directory):
            msg = 'Loader returned a file path outside of the base directory, {}'.format(self.base_directory)
            raise LoadFailed(data_source, self, msg)

        if not exists(rpath):
            msg = 'Loader returned a non-existant file {}'.format(rpath)
            raise LoadFailed(data_source, self, msg)

        if not isdir(rpath):
            msg = 'Loader did not return a directory, but returned {}'.format(rpath)
            raise LoadFailed(data_source, self, msg)

        return rpath

    def load(self, data_source):
        raise NotImplementedError()

    def can_load(self, data_source):
        return False

    def __str__(self):
        return FCN(type(self)) + '()'


class LoadFailed(Exception):
    def __init__(self, data_source, loader, *args):
        msg = args[0]
        mmsg = 'Failed to load {} data with loader {}{}'.format(data_source, loader, ': ' + msg if msg else '')
        super(LoadFailed, self).__init__(mmsg, *args[1:])
