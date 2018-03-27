#!/usr/bin/env python3
# -*- coding: latin-1 -*-
# 
# see http://docs.python.org/dist/dist.html
# 
from distutils.core import setup


setup(name='apycsp',
      version='0.1.0',
      description='aPyCSP - Python CSP Library using asyncio',
      author='John Markus Bjørndalen',
      author_email='jmb@cs.uit.no',
      url='http://www.cs.uit.no/~johnm/code/PyCSP/',
      license='MIT',
      packages=['apycsp', 'apycsp.plugNplay'],
      platforms=['any'],
      )
