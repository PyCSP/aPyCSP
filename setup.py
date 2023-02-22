#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# see http://docs.python.org/dist/dist.html
# https://setuptools.pypa.io/en/latest/userguide/quickstart.html
from setuptools import setup


setup(
    name='apycsp',
    version='0.9.1',
    description='aPyCSP - Python CSP Library using asyncio',
    author='John Markus Bjørndalen',
    author_email='jmb@cs.uit.no',
    url='https://github.com/PyCSP/aPyCSP',
    license='MIT',
    packages=['apycsp', 'apycsp.net'],
    platforms=['any'],
)
