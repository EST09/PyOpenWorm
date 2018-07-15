from __future__ import print_function
import sys
import os
from os.path import exists, abspath, join as pth_join, dirname, isabs, relpath
from os import makedirs, mkdir
import hashlib
import shutil
import json
import logging
try:
    from tempfile import TemporaryDirectory
except ImportError:
    from backports.tempfile import TemporaryDirectory

from .command_util import IVar, SubCommand
from .context import Context


L = logging.getLogger(__name__)


class POWSource(object):
    ''' Commands for working with DataSource objects '''

    def __init__(self, parent):
        self._parent = parent

    # Commands specific to sources
    def create(self, kind, key, *args, **kwargs):
        """
        Create the source and add it to the graph.

        Arguments are determined by the type of the data source

        Parameters
        ----------
        kind : rdflib.term.URIRef
            The kind of source to create
        key : str
            The key, a unique name for the source
        """

    def list(self, context=None):
        """
        List known sources
        """
        from PyOpenWorm.datasource import DataSource
        conf = self._parent._conf()
        # TODO: Pull this string out of here...just dunno where it goes yet
        ctx = Context(ident='http://openworm.org/data', conf=conf)
        dt = ctx.stored(DataSource)(conf=conf)
        nm = conf['rdf.graph'].namespace_manager
        for x in dt.load():
            print(nm.normalizeUri(x.identifier))

    def show(self, data_source):
        '''
        Parameters
        ----------
        data_source : str
            The ID of the data source to show
        '''
        from rdflib.term import URIRef
        from rdflib.namespace import is_ncname
        from PyOpenWorm.datasource import DataSource

        conf = self._parent._conf()
        nm = conf['rdf.graph'].namespace_manager
        parts = data_source.split(':')
        if len(parts) > 1 and is_ncname(parts[1]):
            for pref, ns in nm.namespaces():
                if pref == parts[0]:
                    data_source = URIRef(ns + parts[1])
                    break
        uri = URIRef(data_source)
        print(uri)
        ctx = Context(ident='http://openworm.org/data', conf=conf)
        for x in ctx.stored(DataSource)(ident=uri).load():
            x.fill()
            print(x)

    def list_kinds(self):
        """
        List kinds of sources
        """


class POWTranslator(object):
    def __init__(self, parent):
        self._parent = parent

    def list(self, context=None):
        '''
        List translator types
        '''
        from PyOpenWorm.datasource import DataTranslator
        conf = self._parent._conf()
        # TODO: Pull this string out of here...just dunno where it goes yet
        ctx = Context(ident='http://openworm.org/data', conf=conf)
        dt = ctx.stored(DataTranslator)(conf=conf)
        nm = conf['rdf.graph'].namespace_manager
        for x in dt.load():
            print(nm.normalizeUri(x.identifier))


class POW(object):
    """
    High-level commands for working with PyOpenWorm data
    """

    graph_accessor_finder = IVar(doc='Finds an RDFLib graph from the given URL')

    basedir = IVar('.', doc='The base directory. powdir is resolved against this base')

    repository_provider = IVar(doc='The provider of the repository logic'
                                   ' (cloning, initializing, committing, checkouts)')

    source = SubCommand(POWSource)

    translator = SubCommand(POWTranslator)

    def __init__(self):
        self.progress_reporter = lambda *args, **kwargs: None
        self.message = lambda *args, **kwargs: print(*args, **kwargs)

    @IVar.property('.pow')
    def powdir(self):
        '''
        The base directory for PyOpenWorm files. The repository provider's files also go under here
        '''
        if isabs(self._powdir):
            return self._powdir
        return pth_join(self.basedir, self._powdir)

    @powdir.setter
    def powdir(self, val):
        self._powdir = val

    @IVar.property('pow.conf', value_type=str)
    def config_file(self):
        ''' The config file name '''
        if isabs(self._config_file):
            return self._config_file
        return pth_join(self.powdir, self._config_file)

    @config_file.setter
    def config_file(self, val):
        self._config_file = val

    @IVar.property('worm.db')
    def store_name(self):
        ''' The file name of the database store '''
        if isabs(self._store_name):
            return self._store_name
        return pth_join(self.powdir, self._store_name)

    @store_name.setter
    def store_name(self, val):
        self._store_name = val

    def _ensure_powdir(self):
        if not exists(self.powdir):
            makedirs(self.powdir)

    @IVar.property
    def log_level(self):
        '''
        Log level
        '''
        return logging.getLevelName(logging.getLogger().getEffectiveLevel())

    @log_level.setter
    def log_level(self, level):
        logging.basicConfig()
        logging.getLogger().setLevel(getattr(logging, level))
        logging.getLogger('PyOpenWorm.mapper').setLevel(logging.ERROR)
        # Tailoring for known loggers

    def context(self, context=None):
        '''
        Read or set current target context for the repository
        '''
        ctx_file_name = abspath(pth_join(self.basedir, 'context'))
        if context is not None:
            with open(ctx_file_name, 'w') as f:
                print(context, file=f)
        else:
            if not exists(ctx_file_name):
                self.message('No context')
                return
            with open(ctx_file_name, 'r') as f:
                self.message(f.read())

    def init(self, update_existing_config=False):
        """
        Makes a new graph store.

        The configuration file will be created if it does not exist. If it
        *does* exist, the location of the database store will, by default, not
        be changed in that file

        Parameters
        ----------
        update_existing_config : bool
            If True, updates the existing config file to point to the given
            file for the store configuration
        """
        try:
            self._ensure_powdir()
            if not exists(self.config_file):
                self._init_config_file()
            elif update_existing_config:
                with open(self.config_file, 'r+') as f:
                    conf = json.load(f)
                    conf['rdf.store_conf'] = relpath(abspath(self.store_name),
                                                     abspath(self.basedir))
                    f.seek(0)
                    self._write_config(conf, f)

            self._init_store()
            self._init_repository()
        except Exception as e:
            self._ensure_no_powdir()
            raise e

    def _ensure_no_powdir(self):
        if exists(self.powdir):
            shutil.rmtree(self.powdir)

    def _init_config_file(self):
        with open(self._default_config(), 'r') as f:
            default = json.load(f)
            with open(self.config_file, 'w') as of:
                default['rdf.store_conf'] = relpath(abspath(self.store_name),
                                                    abspath(self.basedir))
                self._write_config(default, of)

    def _write_config(self, conf, dest):
        json.dump(conf, dest, sort_keys=True, indent=4, separators=(',', ': '))
        dest.write('\n')

    def _init_repository(self):
        if self.repository_provider is not None:
            self.repository_provider.init(base=self.powdir)

    def fetch_graph(self, url):
        """
        Fetch a graph

        Parameters
        ----------
        url : str
            URL for the graph
        """
        res = self._obtain_graph_accessor(url)
        if not res:
            raise UnreadableGraphException('Could not read the graph at {}'.format(url))
        return res()

    def add_graph(self, url=None, context=None, include_imports=True):
        """
        Fetch a graph and add it to the local store.

        Parameters
        ----------
        url : str
            The URL of the graph to fetch
        context : rdflib.term.URIRef
            If provided, only this context and, optionally, its imported graphs
            will be added.
        include_imports : bool
            If True, imports of the named context will be included. Has no
            effect if context is None.
        """
        graph = self.fetch_graph(url)
        dat = self._conf()

        dat['rdf.graph'].addN(graph.quads((None, None, None, context)))

    def _obtain_graph_accessor(self, url):
        if self.graph_accessor_finder is None:
            raise Exception('No graph_accessor_finder has been configured')

        return self.graph_accessor_finder(url)

    def _conf(self):
        from PyOpenWorm.data import Data
        dat = getattr(self, '_dat', None)
        if not dat or self._dat_file != self.config_file:
            dat = Data.open(self.config_file)
            stored_conf = dat.get('rdf.store_conf', None)

            if stored_conf and not isabs(stored_conf):
                dat['rdf.store_conf'] = abspath(pth_join(self.basedir, stored_conf))
            dat.init_database()
            self._dat = dat
            self._dat_file = self.config_file
        return dat

    _init_store = _conf

    def clone(self, url=None, update_existing_config=False):
        """Clone a data store

        Parameters
        ----------
        url : str
            URL of the data store to clone
        update_existing_config : bool
            If True, updates the existing config file to point to the given
            file for the store configuration
        """
        try:
            makedirs(self.powdir)
            print('Cloning...', file=sys.stderr)
            with self.progress_reporter(file=sys.stderr, unit=' objects', miniters=0) as progress:
                self.repository_provider.clone(url, base=self.powdir, progress=progress)
            if not exists(self.config_file):
                self._init_config_file()
            self._init_store()
            print('Deserializing...', file=sys.stderr)
            with self.progress_reporter(unit=' ctx', file=sys.stderr) as ctx_prog, \
                    self.progress_reporter(unit=' triples', file=sys.stderr, leave=False) as trip_prog:
                self._load_all_graphs(ctx_prog, trip_prog)
            print('Done!', file=sys.stderr)
        except BaseException as e:
            self._ensure_no_powdir()
            raise e

    def _load_all_graphs(self, progress, trip_prog):
        import transaction
        from rdflib import plugin
        from rdflib.parser import Parser, create_input_source
        idx_fname = pth_join(self.powdir, 'graphs', 'index')
        triples_read = 0
        if exists(idx_fname):
            dest = self._conf()['rdf.graph']
            with open(idx_fname) as index_file:
                cnt = 0
                for l in index_file:
                    cnt += 1
                index_file.seek(0)
                progress.total = cnt
                with transaction.manager:
                    for l in index_file:
                        fname, ctx = l.strip().split(' ')
                        parser = plugin.get('nt', Parser)()
                        with open(pth_join(self.powdir, 'graphs', fname), 'rb') as f, \
                                _BatchAddGraph(dest.get_context(ctx), batchsize=4000) as g:
                            parser.parse(create_input_source(f), g)
                        progress.update(1)
                        triples_read += g.count
                        trip_prog.update(g.count)
                    progress.write('Finalizing writes to database...')
        progress.write('Loaded {:,} triples'.format(triples_read))

    def translate(self, translator, imports_context_ident, output_key=None, *data_sources, **named_data_sources):
        """
        Do a translation with the named translator and inputs

        Parameters
        ----------
        translator : str
            Translator identifier
        imports_context_ident : str
            Identifier for the imports context. All imports go in here
        output_key : str
            Output identifier
        *data_sources : str
            Input data sources
        **named_data_sources : str
            Named input data sources
        """
        from PyOpenWorm.context import Context
        imports_context = Context(ident=imports_context_ident, conf=self._conf())
        translator_class = self._lookup_translator(translator)
        translator = translator_class()
        positional_sources = [self._lookup_source(src) for src in data_sources]
        named_sources = {k: self._lookup_source(src) for k, src in named_data_sources}
        saved_contexts = set([])
        with TemporaryDirectory(prefix='pow-translate') as d:
            orig_wd = os.getcwd()
            os.chdir(d.name)
            try:
                self._unpack_context(d.name)
                res = translator(*positional_sources, output_key=output_key, **named_sources)
                res.data_context.save_context(inline_imports=True, saved_contexts=saved_contexts)
                res.data_context.save_imports(imports_context)
                res.evidence_context.save_context(inline_imports=True, saved_contexts=saved_contexts)
                res.evidence_context.save_imports(imports_context)
            finally:
                os.chdir(orig_wd)

    def _lookup_translator(self, tname):
        from PyOpenWorm.datasource import DataTranslator
        for x in DataTranslator(ident=tname).load():
            return x

    def reconstitute(self, data_source):
        """
        Recreate a data source by executing the chain of translators that went into making it.

        Parameters
        ----------
        data_source : str
            Identifier for the data source to reconstitute
        """

    def serialize(self, destination, format='nquads'):
        '''
        Serialize the graph to a file

        Parameters
        ----------
        destination : file or str
            A file-like object to write the file to or a file name
        format : str
            Serialization format (ex, 'n3', 'nquads')
        '''
        self._conf()['rdf.graph'].serialize(destination, format=format)

    def _package_path(self):
        """
        Get the package path
        """
        from pkgutil import get_loader
        return dirname(get_loader('PyOpenWorm').get_filename())

    def _default_config(self):
        return pth_join(self._package_path(), 'default.conf')

    def list_contexts(self):
        '''
        List contexts
        '''
        for c in self._conf()['rdf.graph'].contexts():
            print(c.identifier)

    @property
    def _rdf(self):
        return self._conf()['rdf.graph']

    def commit(self, message):
        """
        Write the graph to the local repository

        Parameters
        ----------
        message : str
            commit message
        """
        repo = self.repository_provider
        self._serialize_graphs()
        repo.commit(message)

    def _serialize_graphs(self):
        from rdflib import plugin
        from rdflib.serializer import Serializer
        g = self._conf()['rdf.graph']
        repo = self.repository_provider

        repo.base = self.powdir
        graphs_base = pth_join(self.powdir, 'graphs')

        if repo.is_dirty:
            repo.reset()

        if exists(graphs_base):
            repo.remove(['graphs'], recursive=True)
            shutil.rmtree(graphs_base)

        mkdir(graphs_base)
        files = []
        ctx_data = []
        for x in g.contexts():
            ident = x.identifier
            hs = hashlib.sha256(ident.encode()).hexdigest()
            fname = pth_join(graphs_base, hs + '.nt')
            i = 1
            while exists(fname):
                fname = pth_join(graphs_base, hs + '-' + i + '.nt')
                i += 1
            files.append(fname)
            serializer = plugin.get('nt', Serializer)(sorted(x))
            with open(fname, 'wb') as gfile:
                serializer.serialize(gfile)
            ctx_data.append((relpath(fname, graphs_base), ident))

        index_fname = pth_join(graphs_base, 'index')
        with open(index_fname, 'w') as index_file:
            for l in sorted(ctx_data):
                print(*l, file=index_file)

        files.append(index_fname)
        repo.add([relpath(f, self.powdir) for f in files] + [relpath(self.config_file, self.powdir),
                                                             'graphs'])

    def diff(self):
        """
        """
        self._serialize_graphs()

    def merge(self):
        """
        """

    def push(self):
        """
        """

    def tag(self):
        """
        """


class _BatchAddGraph(object):
    ''' Wrapper around graph that turns calls to 'add' into calls to 'addN' '''
    def __init__(self, graph, batchsize=1000, *args, **kwargs):
        self.graph = graph
        self.g = (graph,)
        self.batchsize = batchsize
        self.reset()

    def reset(self):
        self.batch = []
        self.count = 0

    def add(self, triple):
        if self.count > 0 and self.count % self.batchsize == 0:
            self.graph.addN(self.batch)
            self.batch = []
        self.count += 1
        self.batch.append(triple + self.g)

    def __enter__(self):
        self.reset()
        return self

    def __exit__(self, *exc):
        if exc[0] is None:
            self.graph.addN(self.batch)


class UnreadableGraphException(Exception):
    pass


class InvalidGraphException(Exception):
    pass
