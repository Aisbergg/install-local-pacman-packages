# Install Pacman packages from cache
This repository contains a *Python* script for installing self build (e.g. from AUR) *Pacman* packages and their dependencies.

<!-- TOC depthFrom:1 depthTo:6 withLinks:1 updateOnSave:1 orderedList:0 -->

- [Install Pacman packages from cache](#install-pacman-packages-from-cache)
	- [Why another helper?](#why-another-helper)
	- [Requirements](#requirements)
	- [Usage](#usage)
	- [License](#license)

<!-- /TOC -->

---

## Why another helper?
There are a lot great [AUR Helper](https://wiki.archlinux.org/index.php/AUR_helpers) for easy installation of *AUR* packages, so why another?

This script targets only the installation of ready build *AUR* packages that are stored in the *Pacman* package cache. The script will look for a given packagne name in the cache and install it and also its dependencies in order.

## Requirements
Using *PIP* the following command must be executed:

```bash
pip install -r requirements.txt
```

## Usage
Usage is as follows:

```
usage: install-pacman-packages [-h] [-u] [-c CACHE_DIR]
                               package_names [package_names ...]

Install locally cached Pacman packages

positional arguments:
  package_names         Name of the packages to be installed

optional arguments:
  -h, --help            show this help message and exit
  -u, --use-cache-only  Install packages only from local cache
  -c CACHE_DIR, --cachedir CACHE_DIR
                        Path of Pacman's package dir
```

So for example:
```bash
sudo python install-pacman-packages.py -c "/my/package/cache" smartgit
```

the script will look for a cached version of the [`smartgit`](https://aur.archlinux.org/packages/smartgit/) package, figure out its dependencies, install its dependencies and then install the package iteself.

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
