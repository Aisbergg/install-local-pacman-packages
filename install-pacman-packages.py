#!/usr/bin/python3
import argparse
import os
import sys
import re
import tarfile
import time
from subprocess import Popen, PIPE
from distutils.version import LooseVersion

import pacman

pacman_cache_dir = '/var/cache/pacman/pkg'
packages_in_offical_repositories = None
cached_packages = None


class ConsoleColors:
    blue = '\033[94m'
    green = '\033[92m'
    red = '\033[91m'
    yellow = '\033[93m'
    reset = '\033[0m'


class InvalidPacmanPackageError(Exception):
    """Invalid pacman package exception.

    Args:
        message (str): Message passed with the exception

    """

    def __init__(self, message):
        super().__init__(message)


class CachedPackageUnavailable(Exception):
    """Package not available exception.

    Args:
        message (str): Message passed with the exception

    """

    def __init__(self, message):
        super().__init__(message)


def printInfo(message):
    """Print a colorful info message.

    Args:
        message (str): Message to be printed

    """
    print(ConsoleColors.blue + message + ConsoleColors.reset)


def printSuccessfull(message):
    """Print a colorful successfull message.

    Args:
        message (str): Message to be printed

    """
    print(ConsoleColors.green + message + ConsoleColors.reset)


def printWarning(message):
    """Print a colorful warning message.

    Args:
        message (str): Message to be printed

    """
    print(ConsoleColors.yellow + message + ConsoleColors.reset)


def printError(message):
    """Print a colorful error message.

    Args:
        message (str): Message to be printed

    """
    print(ConsoleColors.red + message + ConsoleColors.reset)


class PackageRepository:
    """Represents a simple enum of repositories."""

    OFFICIAL = "official"
    LOCAL = "local"


class PackageBase:
    """Base class for pacman packages."""

    name = None
    version = None
    architecture = None
    repository = None
    dependencies = []
    license = None

    # store for errors
    error_info = None

    # status of the installtion
    #   -2: dependency failed to install
    #   -1: failed to install
    #   0: is not installed
    #   1: is installed
    #   2: different version is installed
    #   3: successfully installed
    #   4: successfully reinstalled
    installation_status = 0

    def __init__(self, name=None):
        self.name = name

    def install(self, force):
        """Install the Pacman package.

        Args:
            force (bool): Force the installation of the package

        """
        raise NotImplementedError("Please Implement this method")

    def get_installation_status(self):
        """Get the installation status of the package."""
        if pacman.is_installed(self.name):
            pcm_info = pacman.get_info(self.name)
            if pcm_info['Version'] == self.version:
                self.installation_status = 1
            else:
                self.installation_status = 2
        else:
            self.installation_status = 0


class CachedPackage(PackageBase):
    """Represents a cached Pacman package.

    Args:
        path (str): Path of the cache file

    """

    path = None

    def __init__(self, path):
        self.path = path
        try:
            self._parse_file_name()
        except Exception as e:
            self.error_info = e

    def _parse_file_name(self):
        """Parse the file name to determine name, version and architecture of the cached package."""
        file_name = os.path.basename(self.path)
        match = re.compile(r'(.+?)-([^-]+-[^-]+)-([^-]+).pkg.tar.xz').search(file_name)
        if match:
            self.name = match.group(1)
            self.version = match.group(2)
            self.architecture = match.group(3)
        else:
            raise InvalidPacmanPackageError("Failed to parse package file name '{0}'".format(self.path))

    def determine_repository(self):
        """Determine the repository from which the package was obtained."""
        # check if package is in official repo
        for pcm_info in packages_in_offical_repositories:
            if pcm_info['id'] == self.name:
                self.repository = PackageRepository.OFFICIAL
                return

        self.repository = PackageRepository.LOCAL

    def _parse_from_string(self, name, string):
        """Parse a value for a param from a string.

        Args:
            name (str): Name of the param to parse
            string (str): String containing all params

        Returns:
            str.  Value for given param
            list.  Value for given param
            None.  If given param wasn't found

        """
        lines = string.splitlines()
        values = []
        for line in lines:
            match = re.compile(r'^{0} = (.+)$'.format(name)).search(line)
            if match:
                values.append(match.group(1))

        if len(values) == 0:
            return None
        elif len(values) == 1:
            return values[0]
        else:
            return values

    def _get_dependencies_from_alias(self, dep_alias_names):
        """Get the real package names if only an alias was supplied.

        Args:
            dep_alias_names (list): (Alias-)Names of the packages

        Returns:
            list.  Real names of the packages

        """
        dependencies = []
        if dep_alias_names:
            for dep_alias_name in dep_alias_names:
                dep_alias_name = re.sub(r'(.+?)(<|<=|>|>=){1}.*?$', r'\1',
                                        dep_alias_name)
                rc, out, err = run_command(['package-query', '-QASiif', '%n', dep_alias_name], False)
                if rc != 0:
                    dependencies.append(out[-1])
                else:
                    dependencies.append(dep_alias_name)

        return dependencies

    def determine_package_info(self):
        """Parse package information from compressed tar file."""
        if self.repository == PackageRepository.LOCAL:
            try:
                tar = tarfile.open(self.path, mode='r:xz')
                pkginfo = None

                for tarinfo in tar:
                    if tarinfo.name == ".PKGINFO":
                        pkginfo = tarinfo.name
                        break

                if not pkginfo and not pkginfo.isfile():
                    tar.close()
                    raise InvalidPacmanPackageError(self.path)

                pkginfo_file_content = tar.extractfile(pkginfo).read().decode("utf-8")
                tar.close()

                dependencies = self._parse_from_string("depend", pkginfo_file_content)
                if dependencies:
                    if type(dependencies) == str:
                        dependencies = [dependencies]
                    self.dependencies = self._get_dependencies_from_alias(dependencies)
                else:
                    self.dependencies = []

                self.architecture = self._parse_from_string("arch", pkginfo_file_content)
                self.license = self._parse_from_string("license", pkginfo_file_content)
            except Exception as e:
                self.error_info = InvalidPacmanPackageError(
                    "Failed to parse package file name '{0}'".format(self.path))

    def install(self, force):
        """Install the Pacman package.

        Args:
            force (bool): Force the installation of the package

        """
        if self.installation_status == 0 or self.installation_status == 2 or force:
            pcm_cmd = ['pacman', '-U', '--noconfirm', '--noprogressbar',
                       '--cachedir', pacman_cache_dir]
            if self.installation_status == 1:
                pcm_cmd += ['--force']
                printInfo("Renstalling package {0} {1}...".format(
                    self.name, self.version))
            else:
                printInfo("Installing package {0} {1}...".format(
                    self.name, self.version))

            rc, out, err = run_command(pcm_cmd + [self.path])
            if rc != 0:
                self.installation_status = -1
                self.error_info = Exception(
                    "Failed to install package {0} {1}: {2}".format(self.name, self.version, '\n'.join(err)))
            else:
                if self.installation_status == 1:
                    self.installation_status = 4
                else:
                    self.installation_status = 3


class OfficialPackage(PackageBase):
    """Represents a Pacman package that is not cached locally.

    Args:
        name (str): Name of the Pacman package

    """

    def __init__(self, name):
        self.name = name
        self.repository = PackageRepository.OFFICIAL
        self.get_installation_status()

    def install(self, force):
        """Install the Pacman package.

        Args:
            force (bool): Force the installation of the package

        """
        pcm_cmd = ['pacman', '-S', '--needed', '--noconfirm', '--noprogressbar',
                   '--cachedir', pacman_cache_dir]
        if self.installation_status == 1:
            pcm_cmd += ['--force']
            printInfo("Renstalling package {0} {1}...".format(
                self.name, self.version))
        else:
            printInfo("Installing package {0} {1}...".format(
                self.name, self.version))

        rc, out, err = run_command(pcm_cmd + [self.name])
        if rc != 0:
            self.installation_status = -1
            self.error_info = Exception(
                "Failed to install package {0}: {1}".format(self.name, '\n'.join(err)))
        else:
            if self.installation_status == 1:
                self.installation_status = 4
            else:
                self.installation_status = 3


def get_cached_package(pkg_name):
    """Get a cached version of a package.

    Args:
        pkg_name (str): Name of the package

    Returns:
        CachedPackage: The cached package for the given name. If the given
                       package is not in cache None is returned.

    """
    pkg = None
    chached_versions = []
    for cached_pkg in cached_packages:
        if cached_pkg.name == pkg_name:
            chached_versions.append(cached_pkg)

    if len(chached_versions) > 0:
        pkg = chached_versions[0]
        for cached_pkg in chached_versions:
            if LooseVersion(pkg.version) < LooseVersion(cached_pkg.version):
                pkg = cached_pkg
        if pkg:
            pkg.get_installation_status()

    return pkg


def get_package_recursive(pkg_name, pkg_dict):
    """Colect information about a package and all their dependencies.

    Args:
        pkg_name (str): Name of the package
        pkg_dict (dict): Store for package information

    """
    if pkg_name in pkg_dict:
        return

    # check if package is in cache
    pkg = get_cached_package(pkg_name)
    if pkg:
        pkg_dict[pkg_name] = pkg
    else:
        # check if the package is already installed
        rc, out, err = run_command(['package-query', '-Qiif', '%n', pkg_name], False)
        real_pkg_name = ""
        if rc == 0:
            real_pkg_name = out[0]
            pkg = get_cached_package(real_pkg_name)
            if pkg:
                pkg_dict[pkg_name] = pkg
                pkg_dict[real_pkg_name] = pkg
            else:
                # check if the package is in a offical repository
                rc, out, err = run_command(['package-query', '-Siif', '%n', pkg_name], False)
                if rc == 0:
                    real_pkg_name = out[-1]
                    pkg = OfficialPackage(real_pkg_name)
                    pkg_dict[pkg_name] = pkg
                    pkg_dict[real_pkg_name] = pkg
                    return

                # package is not in an offical repository and not locally available
                else:
                    pkg = PackageBase(pkg_name)
                    pkg.error_info = CachedPackageUnavailable(
                        "No cached package available for '{0}'".format(pkg_name))
                    pkg_dict[pkg_name] = pkg
                    return

        else:
            # check if the package is in official repo
            rc, out, err = run_command(['package-query', '-Siif', '%n', pkg_name], False)
            if rc == 0:
                real_pkg_name = out[-1]
                pkg = OfficialPackage(real_pkg_name)
                pkg_dict[pkg_name] = pkg
                pkg_dict[real_pkg_name] = pkg
                return

            else:
                rc, out, err = run_command(['package-query', '-Aiif', '%n', pkg_name], False)
                if rc == 0:
                    for rpn in out:
                        pkg = get_cached_package(rpn)
                        if pkg:
                            break

                # package is not locally cached
                if not pkg:
                    pkg = PackageBase(pkg_name)
                    pkg.error_info = CachedPackageUnavailable(
                        "No cached package available for '{0}'".format(pkg_name))
                    pkg_dict[pkg_name] = pkg
                    return

    pkg.determine_repository()
    pkg.determine_package_info()

    # break if package is invalid
    if pkg.error_info:
        return

    if pkg.repository == PackageRepository.LOCAL:
        for dependency in pkg.dependencies:
            get_package_recursive(dependency, pkg_dict)


def install_package_recursive(pkg_name,
                              pkg_dict,
                              use_cache_only,
                              force):
    """Install a package and all their dependencies.

    Args:
        pkg_name (str): Name of the package
        pkg_dict (dict): Store for package information
        use_cache_only (bool): Install packages only from local cache
        force (bool): Force the installation

    """
    pkg = pkg_dict[pkg_name]

    # break if a error occurred
    if pkg.error_info:
        return

    # install official package
    if type(pkg) is OfficialPackage:
        if use_cache_only:
            pkg.error_info = Exception("Official package '{}' not found in cache".format(pkg_name))
        else:
            pkg.install(force)
        return

    # install dependencies first
    for dependency in pkg.dependencies:
        pkg_dependency = pkg_dict[dependency]
        install_package_recursive(dependency, pkg_dict, use_cache_only, force)
        if pkg_dependency.error_info:
            pkg.installation_status = -2
            return

    pkg.install(force)


def format_log(pkg, msg, prefix=''):
    """Format a installation log for a given packge.

    Args:
        pkg (PackageBase): The package
        msg (str): Message for the package
        prefix (str): Prefix added for message in multiple lines

    Returns:
        str.  The formatted installation log

    """
    prefix2 = ' ' * (len(pkg.name) + len(pkg.version) + 3)
    msg_lines = msg.splitlines()
    if len(msg_lines) > 1:
        for i in range(1, len(msg_lines)):
            msg_lines[i] = prefix + prefix2 + msg_lines[i]
        msg = '\n'.join(msg_lines)

    if pkg.version:
        return "{0} {1}: {2}".format(pkg.name, pkg.version, msg)
    return "{0}: {1}".format(pkg.name, msg)


def run_command(command, print_output=True):
    """Run a command in a subprocess.

    Args:
        command (string): Command to run
        print_output (bool): True if the output should be printed to stdout and stderr

    Returns:
        (int, list, list).  Return code of the subprocess, sdtout and stderr

    """
    process = Popen(command, stdout=PIPE, stderr=PIPE, universal_newlines=True)
    if print_output:
        err = []
        out = []
        while True:
            tmp = process.stdout.readline()
            if tmp:
                tmp = tmp.rstrip('\n ')
                if tmp != '':
                    out.append(tmp)
                    print(tmp)
            if process.poll() is not None:
                break
            time.sleep(.05)

        for line in process.stdout.readlines():
            tmp = line.rstrip('\n ')
            out.append(tmp)
            print(tmp)
        rc = process.poll()
        if rc != 0:
            for line in process.stderr.readlines():
                tmp = line.rstrip('\n ')
                printError(tmp)
                err.append(tmp)
        return (rc, out, err)

    else:
        out, err = process.communicate()
        rc = process.returncode
        return (rc, out.splitlines(), err.splitlines())


def print_installation_log_recursive(pkg_names, pkg_dict, prefix='', is_root=False):
    """Recursivly prints a installation log for a given package.

    Args:
        pkg_names (PackageBase): The package
        pkg_dict (dict): Store for package information
        prefix (str): Prefix for the message
        is_root (bool): True if first recursion

    Returns:
        (bool, list).  Tuple consting of the installation status and the log messages as a list

    """
    success = True
    log = []
    log_prefix = prefix + '├── '
    intermediate_prefix = prefix + '|   '
    for pos, anchor, pkg_name in enumerate_package_names(pkg_names):
        pkg = pkg_dict[pkg_name]
        log_dep = []
        if is_root:
            log_prefix = ""
            intermediate_prefix = ""
        elif anchor == 1:
            log_prefix = prefix + '└── '
            intermediate_prefix = prefix + '    '
        if len(pkg.dependencies) > 0:
            success, log_dep = print_installation_log_recursive(
                [dep for dep in pkg.dependencies],
                pkg_dict,
                intermediate_prefix)
        if not success:
            log.append(log_prefix + format_log(
                pkg, "Dependency Failed: " + str(pkg.error_info), intermediate_prefix))
        elif pkg.error_info:
            success = False
            log.append(log_prefix + format_log(
                pkg, "Failed: " + str(pkg.error_info), intermediate_prefix))
        else:
            if pkg.installation_status == 1:
                log.append(log_prefix + format_log(
                    pkg, "Skipped"))
            elif pkg.installation_status == 3:
                log.append(log_prefix + format_log(
                    pkg, "Successfully installed"))
            elif pkg.installation_status == 4:
                log.append(log_prefix + format_log(
                    pkg, "Successfully reinstalled"))

        log = log + log_dep

    return success, log


def print_installation_log(pkg_name, pkg_dict):
    """Print a installation log for a given package.

    Args:
        pkg_names (PackageBase): The package
        pkg_dict (dict): Store for package information

    """
    successfully_installed, log = print_installation_log_recursive(
        [pkg_name], pkg_dict, '', True)
    for line in log:
        if successfully_installed:
            printSuccessfull(line)
        else:
            printError(line)


def enumerate_package_names(sequence):
    length = len(sequence)
    for count, value in enumerate(sequence):
        yield count, length - count, value


def main(argv):
    """Run the main logic.

    Args:
        argv (list): Command line arguments

    """
    parser = argparse.ArgumentParser(
        prog='install-pacman-packages',
        description='Install locally cached Pacman packages',
        epilog=''
    )
    parser.add_argument('-u', '--use-cache-only', action='store_true',
                        dest='use_cache_only', default=False,
                        help="Install packages only from local cache")
    parser.add_argument('-c', '--cachedir', dest='cache_dir', default='/var/cache/pacman/pkg',
                        help="Path of Pacman's package dir")
    parser.add_argument('-f', '--force', action='store_true',
                        dest='force', default=False,
                        help="Force installation of the package")
    parser.add_argument('package_names', nargs='+',
                        help="Name of the packages to be installed")
    args = parser.parse_args(argv)

    if (os.geteuid() != 0):
        printError("This script needs to be run as root!")
        exit(1)

    global pacman_cache_dir, packages_in_offical_repositories, cached_packages
    packages_in_offical_repositories = pacman.get_available()

    pacman_cache_dir = args.cache_dir
    # generate list of packages in cache
    cached_packages = []
    for f in os.listdir(pacman_cache_dir):
        full_path = os.path.join(pacman_cache_dir, f)
        if os.path.isfile(full_path) and full_path.endswith('.pkg.tar.xz'):
            cached_packages.append(CachedPackage(full_path))

    pkg_dict = dict()
    package_names = [x.lower() for x in args.package_names]

    # collect information about the package and their dependencies
    for pkg_name in package_names:
        get_package_recursive(pkg_name, pkg_dict)

    # install the package and their dependencies
    for pkg_name in package_names:
        install_package_recursive(pkg_name, pkg_dict, args.use_cache_only, args.force)

    # print installation statistics
    printInfo("\nInstallation Statistics:")
    for pkg_name in package_names:
        print_installation_log(pkg_name, pkg_dict)


try:
    main(sys.argv[1:])
    exit(0)
except Exception as e:
    printError(str(e))
    exit(1)
