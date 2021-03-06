#!/usr/local/bin/python3

import getopt
import logging
import logging.config
import os
import sys
import tempfile

def PrintDifferences(diffs):
    for type in diffs:
        if type == "Packages":
            pkg_diffs = diffs[type]
            for (pkg, op, old) in pkg_diffs:
                if op == "delete":
                    print("Delete package %s" % pkg.Name(), file=sys.stderr)
                elif op == "install":
                    print("Install package %s-%s" % (pkg.Name(), pkg.Version()), file=sys.stderr)
                elif op == "upgrade":
                    print("Upgrade package %s %s->%s" % (pkg.Name(), old.Version(), pkg.Version()), file=sys.stderr)
                else:
                    print("Unknown package operation %s for packge %s-%s" % (op, pkg.Name(), pkg.Version()), file=sys.stderr)
        elif type == "Restart":
            from freenasOS.Update import GetServiceDescription
            for svc in diffs[type]:
                desc = GetServiceDescription(svc)
                if desc:
                    print("%s" % desc)
                else:
                    print("Unknown service restart %s?!" % svc)
        elif type in ("Train", "Sequence"):
            # Train and Sequence are a single tuple, (old, new)
            old, new = diffs[type]
            print("%s %s -> %s" % (type, old, new), file=sys.stderr)
        elif type == "Reboot":
            rr = diffs[type]
            print("Reboot is (conditionally) %srequired" % ("" if rr else "not "), file=sys.stderr)
        else:
            print("*** Unknown key %s (value %s)" % (type, str(diffs[type])), file=sys.stderrr)

def main():
    global log

    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': True,
        'formatters': {
            'simple': {
                'format': '[%(name)s:%(lineno)s] %(message)s',
            },
        },
        'handlers': {
            'std': {
                'class': 'logging.StreamHandler',
                'level': 'DEBUG',
                'stream': 'ext://sys.stderr',
            },
        },
        'loggers': {
            '': {
                'handlers': ['std'],
                'level': 'DEBUG',
                    'propagate': True,
            },
        },
    })

    log = logging.getLogger('freenas-update')

    sys.path.append("/usr/local/lib")

    import freenasOS.Configuration as Configuration
    import freenasOS.Manifest as Manifest
    import freenasOS.Update as Update

    def usage():
        print("""Usage: %s [-C cache_dir] [-d] [-T train] [--no-delta] [-v] <cmd>, where cmd is one of:
        check\tCheck for updates
        update\tDo an update""" % sys.argv[0], file=sys.stderr)
        sys.exit(1)

    try:
        short_opts = "C:dT:v"
        long_opts = [ "cache=",
                      "debug",
                      "train=",
                      "verbose",
                      "no-delta"
                      ]
        opts, args = getopt.getopt(sys.argv[1:], short_opts, long_opts)
    except getopt.GetoptError as err:
        print(str(err))
        usage()

    verbose = False
    debug = 0
    config = None
    cache_dir = None
    train = None
    pkg_type = None
    
    for o, a in opts:
        if o in ("-v", "--verbose"):
            verbose = True
        elif o in ("-d", "--debug"):
            debug += 1
        elif o in ('-C', "--cache"):
            cache_dir = a
        elif o in ("-T", "--train"):
            train = a
        elif o in ("--no-delta"):
            pkg_type = Update.PkgFileFullOnly
        else:
            assert False, "unhandled option %s" % o

    config = Configuration.Configuration()
    if train is None:
        train = config.SystemManifest().Train()

    if len(args) != 1:
        usage()

    if args[0] == "check":
        # To see if we have an update available, we
        # call Update.DownloadUpdate.  If we have been
        # given a cache directory, we pass that in; otherwise,
        # we make a temporary directory and use that.  We
        # have to clean up afterwards in that case.
        
        if cache_dir is None:
            download_dir = tempfile.mkdtemp(prefix = "UpdateCheck-", dir = config.TemporaryDirectory())
            if download_dir is None:
                print("Unable to create temporary directory", file=sys.stderr)
                sys.exit(1)
        else:
            download_dir = cache_dir

        rv = Update.DownloadUpdate(train, download_dir, pkg_type = pkg_type)
        if rv is False:
            if verbose:
                print("No updates available")
            if cache_dir is None:
                Update.RemoveUpdate(download_dir)
            sys.exit(1)
        else:
            diffs = Update.PendingUpdatesChanges(download_dir)
            if diffs is None or len(diffs) == 0:
                print("Strangely, DownloadUpdate says there updates, but PendingUpdates says otherwise", file=sys.stderr)
                sys.exit(1)
            PrintDifferences(diffs)
            if cache_dir is None:
                Update.RemoveUpdate(download_dir)
            sys.exit(0)

    elif args[0] == "update":
        # This will attempt to apply an update.
        # If cache_dir is given, then we will only check that directory,
        # not force a download if it is already there.  If cache_dir is not
        # given, however, then it downloads.  (The reason is that you would
        # want to run "freenas-update -c /foo check" to look for an update,
        # and it will download the latest one as necessary, and then run
        # "freenas-update -c /foo update" if it said there was an update.
        try:
            update_opts, update_args = getopt.getopt(args[1:], "R", "--reboot")
        except getopt.GetoptError as err:
            print(str(err))
            usage()

        force_reboot = False
        for o, a in update_opts:
            if o in ("-R", "--reboot"):
                force_reboot = True
            else:
                assert False, "Unhandled option %s" % o
        
        if cache_dir is None:
            download_dir = tempfile.mkdtemp(prefix = "UpdateUpdate-", dir = config.TemporaryDirectory())
            if download_dir is None:
                print("Unable to create temporary directory", file=sys.stderr)
                sys.exit(1)
            rv = Update.DownloadUpdate(train, download_dir, pkg_type = pkg_type)
            if rv is False:
                if verbose or debug:
                    print("DownloadUpdate returned False", file=sys.stderr)
                sys.exit(1)
        else:
            download_dir = cache_dir
        
        diffs = Update.PendingUpdatesChanges(download_dir)
        if diffs is None or diffs == {}:
            if verbose:
                print("No updates to apply", file=sys.stderr)
        else:
            if verbose:
                PrintDifferences(diffs)
            try:
                rv = Update.ApplyUpdate(download_dir, force_reboot = force_reboot)
            except BaseException as e:
                print("Unable to apply update: %s" % str(e), file=sys.stderr)
                sys.exit(1)
            if cache_dir is None:
                Update.RemoveUpdate(download_dir)    
            if rv:
                print("System should be rebooted now", file=sys.stderr)
            sys.exit(0)
    else:
        usage()

if __name__ == "__main__":
    sys.exit(main())

