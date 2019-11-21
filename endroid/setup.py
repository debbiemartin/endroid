#!/usr/bin/env python
#
# EnDroid setup file
#

import re

from distutils.core import setup


# Get the version from the endroid package
ver_re = re.compile(r"\s*__version__\s*=\s*[\"'](?P<version>[^\"']+)")
version_file = 'src/endroid/__init__.py'

version = None
with open(version_file, 'r') as f:
    for line in f.readlines():
        m = ver_re.match(line)
        if m:
            version = m.group('version')
            break

if version is None:
    print("Failed to find version number from {}, aborting setup".format(version_file))
else:
    setup(name='endroid',
          version=version,
          description='EnDroid: a modular XMPP bot',
          url='http://open.ensoft.co.uk/EnDroid',
          packages=[
              'endroid',
              'endroid.plugins',
              'endroid.plugins.compute',
              'endroid.plugins.sms',
          ],
          package_dir={'endroid': 'src/endroid'},
          requires=['treq', 'wokkel', 'twisted']
          )
