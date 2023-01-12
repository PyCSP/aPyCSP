#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# see http://docs.python.org/dist/dist.html
#
from distutils.core import setup


setup(name='apycsp',
      version='0.2.0',
      description='aPyCSP - Python CSP Library using asyncio',
      author='John Markus Bjørndalen',
      author_email='jmb@cs.uit.no',
      url='https://github.com/PyCSP/aPyCSP',
      license='MIT',
      packages=['apycsp', 'apycsp.plugNplay', 'apycsp.net'],
      platforms=['any'],
      )
